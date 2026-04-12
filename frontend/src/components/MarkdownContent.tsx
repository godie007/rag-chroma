import { useEffect, useState, type ComponentPropsWithoutRef } from 'react'
import Markdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

function usePrefersDark(): boolean {
  const [dark, setDark] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)').matches : false,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return dark
}

type CodeProps = ComponentPropsWithoutRef<'code'> & { className?: string }

export function MarkdownContent({ content }: { content: string }) {
  const dark = usePrefersDark()
  const prismStyle = dark ? oneDark : oneLight

  const components: Components = {
    pre({ children }) {
      return <>{children}</>
    },
    code({ className, children, ...rest }: CodeProps) {
      const text = String(children ?? '').replace(/\n$/, '')
      const match = /language-(\w+)/.exec(className ?? '')
      if (match) {
        const lang = match[1] === 'ts' ? 'typescript' : match[1]
        return (
          <SyntaxHighlighter
            style={prismStyle}
            language={lang}
            PreTag="div"
            customStyle={{
              margin: '0.65rem 0',
              borderRadius: '8px',
              fontSize: '0.82rem',
              lineHeight: 1.45,
            }}
            wrapLongLines
          >
            {text}
          </SyntaxHighlighter>
        )
      }
      return (
        <code className="md-inline-code" {...rest}>
          {children}
        </code>
      )
    },
  }

  return (
    <Markdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </Markdown>
  )
}
