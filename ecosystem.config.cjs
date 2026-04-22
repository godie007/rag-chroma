/**
 * PM2: backend (uvicorn) + frontend (Vite) detrás de nginx (:80 → :3333 / :4444).
 *
 * Uso en el servidor:
 *   npm install -g pm2
 *   cd ~/rag-chroma && pm2 start ecosystem.config.cjs
 *   pm2 save && pm2 startup  # seguir la línea que imprime (sudo …)
 *
 * Opcional: export PM2_NODE_BIN=/ruta/al/bin/node si tu versión NVM no es v20.20.2
 */
const path = require('path')
const os = require('os')
const fs = require('fs')

const home = os.homedir()
const root = path.join(home, 'rag-chroma')
const nodeDefault = path.join(home, '.nvm/versions/node/v20.20.2/bin/node')
let nodeBin = process.env.PM2_NODE_BIN || nodeDefault
if (!fs.existsSync(nodeBin)) {
  const nvmNodeDir = path.join(home, '.nvm/versions/node')
  try {
    const versions = fs.readdirSync(nvmNodeDir).filter((v) => v.startsWith('v'))
    versions.sort()
    const latest = versions[versions.length - 1]
    if (latest) nodeBin = path.join(nvmNodeDir, latest, 'bin/node')
  } catch {
    void 0
  }
}

const viteJs = path.join(root, 'frontend/node_modules/vite/bin/vite.js')

module.exports = {
  apps: [
    {
      name: 'whatsapp-gowa-bridge',
      cwd: path.join(root, 'backend'),
      script: path.join(root, 'backend/.venv/bin/python'),
      args: '-m uvicorn app.whatsapp_gowa_bridge:app --host 127.0.0.1 --port 8090',
      interpreter: 'none',
      autorestart: true,
      max_restarts: 30,
      min_uptime: '5s',
      exp_backoff_restart_delay: 2000,
      env: {
        GOWA_UPSTREAM_URL: 'http://127.0.0.1:3000',
      },
    },
    {
      name: 'rag-backend',
      cwd: path.join(root, 'backend'),
      script: path.join(root, 'backend/.venv/bin/python'),
      args: '-m uvicorn app.main:app --host 127.0.0.1 --port 3333',
      interpreter: 'none',
      autorestart: true,
      max_restarts: 30,
      min_uptime: '5s',
      exp_backoff_restart_delay: 2000,
    },
    {
      name: 'rag-frontend',
      cwd: path.join(root, 'frontend'),
      script: viteJs,
      args: '--host 127.0.0.1 --port 4444',
      interpreter: nodeBin,
      autorestart: true,
      max_restarts: 30,
      min_uptime: '5s',
      exp_backoff_restart_delay: 2000,
    },
  ],
}
