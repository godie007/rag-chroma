import io
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import fitz
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pip install pytesseract Pillow
    pytesseract = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

logger = logging.getLogger("rag_qc")


@contextmanager
def _quiet_pypdf_logs():
    loggers = [logging.getLogger(name) for name in ("pypdf", "pypdf._reader", "pypdf.generic")]
    previous = [(lg, lg.level, lg.propagate) for lg in loggers]
    try:
        for lg in loggers:
            lg.setLevel(logging.ERROR)  # solo errores graves durante la extracción
            lg.propagate = False  # no subir ruido al logger raíz
        yield
    finally:
        for lg, level, propagate in previous:
            lg.setLevel(level)  # restaurar nivel anterior
            lg.propagate = propagate


def _looks_like_markdown_table_row(line: str) -> bool:
    """Evita que la limpieza de PDF borre filas de tablas en Markdown (| celdas |)."""
    s = line.strip()
    if not s.startswith("|"):
        return False
    if "---" in s:
        return True
    if not s.endswith("|"):
        return False
    cells = [c.strip() for c in s.split("|")]
    cells = [c for c in cells if c != ""]
    if not cells:
        return False
    return True


def _escape_md_table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _matrix_to_markdown_table(rows: list | None) -> str:
    """Convierte matriz de celdas (p. ej. Table.extract()) a tabla GFM."""
    if not rows:
        return ""
    norm: list[list[str]] = []
    for row in rows:
        if row is None:
            continue
        norm.append(["" if c is None else str(c) for c in row])
    if not norm:
        return ""
    ncols = max(len(r) for r in norm)
    esc = [[_escape_md_table_cell(c) for c in (r + [""] * (ncols - len(r)))] for r in norm]
    sep = "| " + " | ".join(["---"] * ncols) + " |"
    out_lines = ["| " + " | ".join(esc[0]) + " |", sep]
    out_lines.extend("| " + " | ".join(r) + " |" for r in esc[1:])
    return "\n".join(out_lines)


def _page_tables_markdown(page: fitz.Page, page_no: int) -> str:
    """Detecta tablas con PyMuPDF y las serializa en Markdown legible para el LLM."""
    try:
        tf = page.find_tables()
    except Exception as exc:
        logger.debug("find_tables omitido en página %s: %s", page_no, exc)
        return ""
    if not tf.tables:
        return ""
    ordered = sorted(tf.tables, key=lambda t: (round(t.bbox[1], 2), round(t.bbox[0], 2)))
    chunks: list[str] = []
    for i, tab in enumerate(ordered, start=1):
        md = ""
        try:
            md = (tab.to_markdown(clean=True) or "").strip()
        except Exception:
            try:
                md = (tab.to_markdown() or "").strip()
            except Exception:
                md = ""
        if not md:
            try:
                rows = tab.extract()
                md = _matrix_to_markdown_table(rows).strip()
            except Exception:
                md = ""
        if md:
            chunks.append(f"### Tabla {i} (página {page_no})\n\n{md}")
    if not chunks:
        return ""
    return "\n\n".join(chunks)


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")  # unificar saltos de línea
    text = re.sub(r"[ \t]+\n", "\n", text)  # quitar espacios al final de cada línea
    text = re.sub(r"\n{3,}", "\n\n", text)  # no dejar más de un párrafo vacío seguido
    return text.strip()


def merge_short_split_fragments(
    parts: list[str],
    *,
    min_chars: int,
    hard_max: int,
) -> list[str]:
    chunks = [p.strip() for p in parts if p and p.strip()]  # descartar trozos vacíos
    if not chunks:
        return []
    out: list[str] = []
    buf = chunks[0]
    for nxt in chunks[1:]:
        if len(buf) >= min_chars:
            out.append(buf)
            buf = nxt
            continue
        sep = "\n\n" if buf and nxt else ""
        candidate = buf + sep + nxt
        if len(candidate) <= hard_max:
            buf = candidate
        else:
            out.append(buf)
            buf = nxt
    if out and len(buf) < min_chars:
        sep = "\n\n" if out[-1] and buf else ""
        combined = out[-1] + sep + buf
        if len(combined) <= hard_max:
            out[-1] = combined
        else:
            out.append(buf)
    else:
        out.append(buf)
    return out


def build_ingest_recursive_splitter(
    chunk_size: int, chunk_overlap: int
) -> RecursiveCharacterTextSplitter:
    """Separadores de mayor a menor estructura (normas, libros, Markdown). `keep_separator` conserva encabezados en el trozo."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
        keep_separator=True,
        separators=[
            "\n\n## ",
            "\n\n### ",
            "\n\n#### ",
            "\n\nCapítulo ",
            "\n\nArt. ",
            "\n\nArtículo ",
            "\n\nNumeral ",
            "\n\n",
            "\n",
            ". ",
            " ",
            "",
        ],
    )


def build_ingest_code_splitter(
    chunk_size: int, chunk_overlap: int
) -> RecursiveCharacterTextSplitter:
    """Bloques ```; separadores acordes a código sin forzar estructura de prosa normativa."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
        keep_separator=True,
        separators=["\n\n", "\n", " ", ""],
    )


def _iter_markdown_fenced_segments(text: str) -> list[tuple[Literal["prose", "fence"], str]]:
    segments: list[tuple[Literal["prose", "fence"], str]] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find("```", i)  # buscar inicio de bloque de código markdown
        if j == -1:
            if i < n:
                segments.append(("prose", text[i:]))  # resto del texto es prosa
            break
        if j > i:
            segments.append(("prose", text[i:j]))  # texto antes del fence
        line_end = text.find("\n", j + 3)
        if line_end == -1:
            segments.append(("prose", text[j:]))  # ``` sin cierre: tratar como prosa
            break
        k = text.find("```", line_end + 1)  # cierre del bloque ```
        if k == -1:
            segments.append(("prose", text[j:]))
            break
        segments.append(("fence", text[j : k + 3]))  # bloque completo ```…```
        i = k + 3
    return segments


def chunk_text_for_ingest(
    text: str,
    prose_splitter: RecursiveCharacterTextSplitter,
    *,
    chunk_size: int,
    chunk_overlap: int,
    merge_min_chars: int,
    merge_hard_max: int,
    code_splitter: RecursiveCharacterTextSplitter | None = None,
) -> list[str]:
    if code_splitter is None:
        code_splitter = build_ingest_code_splitter(chunk_size, chunk_overlap)
    raw: list[str] = []
    for kind, body in _iter_markdown_fenced_segments(text):  # separar prosa vs ```código```
        b = body.strip() if kind == "fence" else body
        if not (b if kind == "fence" else b.strip()):
            continue
        if kind == "fence":
            if len(b) <= merge_hard_max:
                raw.append(b)  # bloque de código cabe en un solo chunk
            else:
                raw.extend(code_splitter.split_text(b))  # partir el código en varios trozos
        else:
            raw.extend(prose_splitter.split_text(b))  # partir prosa con separadores del PDF/libro
    return merge_short_split_fragments(  # juntar títulos sueltos con el párrafo siguiente
        raw,
        min_chars=merge_min_chars,
        hard_max=max(merge_hard_max, merge_min_chars),
    )


def strip_pdf_glyph_tokens(text: str) -> str:
    if not text:
        return text
    s = re.sub(r"(?:/g\d+)+", " ", text, flags=re.IGNORECASE)  # basura tipo /g123 del stream PDF
    s = re.sub(r" {2,}", " ", s)  # compactar espacios tras limpiar
    return s


def sanitize_chunk_text(text: str) -> str:
    if not text or not text.strip():
        return text
    normalized = _normalize_pdf_stream_junk(text)  # quitar artefactos de operadores PDF
    thinned = _reduce_pdf_drawing_artifacts(normalized)  # tirar líneas tipo tablas vectoriales
    final = clean_text(thinned)  # normalizar espacios y párrafos
    return final if final.strip() else text


def _normalize_pdf_stream_junk(text: str) -> str:
    out_lines: list[str] = []
    for line in text.split("\n"):
        if _looks_like_markdown_table_row(line):
            out_lines.append(line.rstrip())
            continue
        s = line
        s = re.sub(r"(?:/g\d+)+", " ", s, flags=re.IGNORECASE)  # tokens /gN por línea
        s = re.sub(r"(?:[ \t]*\|[ \t]*){2,}", " ", s)  # secuencias de | típicas de dibujo PDF
        s = re.sub(r" {3,}", " ", s)  # espacios múltiples
        out_lines.append(s.rstrip())
    return "\n".join(out_lines)


def _reduce_pdf_drawing_artifacts(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        if _looks_like_markdown_table_row(line):
            out.append(line)
            continue
        s = line.strip()
        if not s:
            out.append("")  # conservar línea en blanco para estructura
            continue
        pipes = s.count("|")
        letters = sum(1 for c in s if c.isalpha())
        digits = sum(1 for c in s if c.isdigit())
        if pipes >= 6 and letters < max(4, pipes // 3):
            continue  # línea dominada por |: probable figura vectorial
        if pipes >= 2 and letters == 0 and digits == 0:
            continue  # solo separadores, sin contenido legible
        stripped_non_alpha = re.sub(r"[^a-zA-Z]", "", s)
        if len(stripped_non_alpha) <= 2 and letters <= 2 and len(s) <= 20:
            non_digit_non_space = re.sub(r"[\d\s\.\,\-\−\+]", "", s)
            if len(non_digit_non_space) <= 2:
                continue  # ruido muy corto (símbolos sueltos)
        out.append(line)
    joined = "\n".join(out)
    joined = re.sub(r"\n{4,}", "\n\n\n", joined)  # limitar párrafos vacíos consecutivos
    return joined.strip()


def _pdf_text_pymupdf(data: bytes, *, find_tables_max_pages: int = 0) -> str:
    """find_tables_max_pages: 0 = en todas las págs; N>0 = solo 1..N (ahorra mucho en PDFs masivos)."""
    doc = fitz.open(stream=data, filetype="pdf")  # abrir PDF desde memoria
    try:
        parts: list[str] = []
        for i in range(doc.page_count):
            page = doc.load_page(i)  # página i-ésima
            page_no = i + 1
            try:
                txt = page.get_text(sort=True)  # orden de lectura humano cuando existe API
            except (TypeError, ValueError):
                txt = page.get_text()  # fallback si sort=True no está soportado
            body = (txt or "").strip()
            if find_tables_max_pages > 0 and page_no > find_tables_max_pages:
                tables_md = ""
            else:
                tables_md = _page_tables_markdown(page, page_no)
            if tables_md:
                block = (
                    f"{body}\n\n---\n\n## Tablas (extracción estructurada, Markdown)\n\n{tables_md}"
                    if body
                    else f"## Tablas (extracción estructurada, Markdown)\n\n{tables_md}"
                )
                parts.append(block)
            else:
                parts.append(body)
        return "\n\n".join(parts)  # separar páginas con doble salto
    finally:
        doc.close()  # liberar recursos del documento


def _pdf_text_pypdf(data: bytes) -> str:
    with _quiet_pypdf_logs():  # evitar inundar logs con avisos de pypdf
        reader = PdfReader(io.BytesIO(data), strict=False)  # lector tolerante a PDFs raros
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")  # texto plano por página
    return "\n\n".join(parts)


def _ocr_one_page_pytesseract(page: fitz.Page, *, dpi: int, lang: str) -> str:
    """Una página: raster en escala de grises (rápida) + Tesseract. Nada si falla el binario o dependencias."""
    if pytesseract is None or Image is None:
        return ""
    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    except (RuntimeError, ValueError) as e:
        logger.debug("OCR get_pixmap: %s", e)
        return ""
    if pix.width < 2 or pix.height < 2:
        return ""
    try:
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    except Exception as e:
        logger.debug("OCR PIL: %s", e)
        return ""
    for lang_try in (lang, "eng"):
        try:
            out = pytesseract.image_to_string(
                img,
                lang=lang_try,
                config="--oem 1 --psm 3",
            )
            t = (out or "").strip()
            if t:
                return t
        except Exception as e:
            if lang_try == lang:
                logger.debug("OCR tesseract (lang=%s): %s", lang_try, e)
            continue
    return ""


def _pdf_ocr_sweep(
    data: bytes,
    *,
    max_pages: int,
    dpi: int,
    lang: str,
) -> str:
    """OCR por páginas (cap acotado) solo para PDFs escaneados. Requiere `tesseract` en PATH (brew/apt)."""
    if max_pages < 1:
        return ""
    if pytesseract is None:
        logger.warning("OCR desactivado: instale pytesseract y Pillow (pip install -r requirements.txt).")
        return ""
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        logger.warning("OCR desactivado: Tesseract no disponible en PATH (%s). macOS: brew install tesseract tesseract-lang", e)
        return ""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        n = min(doc.page_count, max_pages)
        if doc.page_count > max_pages:
            logger.info(
                "OCR: %s de %s págs. (aumenta PDF_OCR_MAX_PAGES o divide el PDF si falta el final).",
                n,
                doc.page_count,
            )
        parts: list[str] = []
        for i in range(n):
            if i > 0 and i % 20 == 0:
                logger.info("OCR: van %s / %s págs.", i + 1, n)
            page = doc.load_page(i)
            t = _ocr_one_page_pytesseract(page, dpi=dpi, lang=lang)
            if t:
                parts.append(f"--- Página {i + 1} ---\n\n{t}")
        return "\n\n".join(parts)
    finally:
        doc.close()


def load_document_bytes(
    filename: str,
    data: bytes,
    *,
    find_tables_max_pages: int = 0,
    pdf_ocr_enabled: bool = True,
    pdf_ocr_max_pages: int = 0,
    pdf_ocr_trigger_total_text: int = 800,
    pdf_ocr_dpi: int = 120,
    pdf_ocr_lang: str = "spa+eng",
) -> str:
    """``find_tables_max_pages``: PyMuPDF; 0=sin límite. ``pdf_ocr_*``: barrido Tesseract si el nativo aporta poco texto."""
    suffix = Path(filename).suffix.lower()  # extensión para elegir extractor
    if suffix in {".txt", ".md", ".markdown"}:
        return clean_text(data.decode("utf-8", errors="replace"))  # UTF-8; bytes inválidos → carácter sustituto
    if suffix == ".pdf":
        raw = ""
        try:
            raw = _pdf_text_pymupdf(
                data, find_tables_max_pages=find_tables_max_pages
            )  # extracción preferida: mejor orden de lectura
        except Exception as e:
            logger.warning("PyMuPDF no disponible o falló (%s); usando pypdf.", e)
        if len(raw.strip()) < 200:
            try:
                raw = _pdf_text_pypdf(data)  # poco texto: reintentar con pypdf por si acaso
            except Exception as e:
                raise ValueError(f"No se pudo leer el PDF: {e}") from e
        elif not raw.strip():
            raw = _pdf_text_pypdf(data)  # PyMuPDF devolvió vacío: probar respaldo
        normalized = _normalize_pdf_stream_junk(raw)  # limpiar operadores residuales
        cleaned = clean_text(_reduce_pdf_drawing_artifacts(normalized))  # quitar basura visual y normalizar
        if (
            pdf_ocr_enabled
            and pdf_ocr_max_pages > 0
            and len(cleaned.strip()) < pdf_ocr_trigger_total_text
        ):
            ocr_raw = _pdf_ocr_sweep(
                data,
                max_pages=pdf_ocr_max_pages,
                dpi=pdf_ocr_dpi,
                lang=pdf_ocr_lang,
            )
            if len(ocr_raw.strip()) > len(cleaned.strip()):
                logger.info(
                    "OCR sustituye extracción nativa (%s → %s caracteres aprox).",
                    len(cleaned.strip()),
                    len(ocr_raw.strip()),
                )
                raw = ocr_raw
                normalized = _normalize_pdf_stream_junk(raw)
                cleaned = clean_text(_reduce_pdf_drawing_artifacts(normalized))
        if not cleaned.strip():
            raise ValueError(
                "El PDF no devolvió texto legible (capa de texto escasa y OCR sin resultados: "
                "compruebe tesseract y datos spa+eng, o un PDF con solo imagen y sin motor OCR)."
            )
        return cleaned
    raise ValueError(f"Formato no soportado: {suffix}. Use .txt, .md o .pdf.")
