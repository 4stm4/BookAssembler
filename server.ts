// The web gateway: the UI and, under /api/v1, the Python API behind it.
//
// Everything the UI does goes to /api/v1 (src/api/client.ts), and this
// server only passes it on to the FastAPI backend - the one place the work
// is done. It used to hold a second, in-memory API of its own (/api/config,
// /api/chapters, /api/figures, /api/jobs, ...) that no screen called.
import express from 'express';
import cors from 'cors';
import path from 'path';
import { createHmac, timingSafeEqual } from 'crypto';
import type { IncomingMessage } from 'http';
import type { Socket } from 'net';
import dotenv from 'dotenv';
import { spawn } from 'child_process';
import { createProxyMiddleware } from 'http-proxy-middleware';

dotenv.config();

const app = express();
const PORT = 3000;

// The longest request the API serves: the book's assembly runs XeLaTeX
// twice, each pass allowed 30 minutes (latex_builder.compile_xelatex), with
// the diagrams vectorized before it. At the 10 minutes this used to be a big
// book came back as a proxy error while its PDF was still being set.
const API_TIMEOUT_MS = 2 * 60 * 60 * 1000;

app.use(cors());

// The login for the UI and the API behind it: KAE_AUTH_USER (default
// "admin") and KAE_AUTH_PASSWORD. The browser asks once (HTTP Basic); a
// session cookie then carries it to the job's WebSocket too, where not
// every browser sends Basic credentials. Without a password the gateway is
// open - `npm run dev` on one's own machine; docker-compose.yml does not
// start without one.
const AUTH_USER = process.env.KAE_AUTH_USER || 'admin';
const AUTH_PASSWORD = process.env.KAE_AUTH_PASSWORD || '';
const SESSION_COOKIE = 'kae_session';
const SESSION = AUTH_PASSWORD
  ? createHmac('sha256', AUTH_PASSWORD).update(`kae-session:${AUTH_USER}`).digest('hex')
  : '';

function same(given: string, expected: string): boolean {
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** How the request proves the login: 'basic', 'cookie', or null for not at all. */
function login(req: IncomingMessage): 'basic' | 'cookie' | null {
  for (const part of (req.headers.cookie ?? '').split(';')) {
    const [name, value] = part.trim().split('=', 2);
    if (name === SESSION_COOKIE && value && same(value, SESSION)) return 'cookie';
  }
  const header = req.headers.authorization ?? '';
  if (header.startsWith('Basic ')) {
    const pair = Buffer.from(header.slice(6), 'base64').toString('utf8');
    const colon = pair.indexOf(':');
    if (colon >= 0 && same(pair.slice(0, colon), AUTH_USER)
        && same(pair.slice(colon + 1), AUTH_PASSWORD)) {
      return 'basic';
    }
  }
  return null;
}

if (AUTH_PASSWORD) {
  app.use((req, res, next) => {
    const how = login(req);
    if (how === null) {
      res.set('WWW-Authenticate', 'Basic realm="BookAssembler", charset="UTF-8"');
      res.status(401).send('Login required');
      return;
    }
    if (how === 'basic') {
      res.append('Set-Cookie', `${SESSION_COOKIE}=${SESSION}; Path=/; HttpOnly; SameSite=Strict`);
    }
    next();
  });
} else {
  console.warn('KAE_AUTH_PASSWORD is not set: the UI and the API are open to anyone who reaches this port.');
}

const apiProxy = createProxyMiddleware({
  target: 'http://127.0.0.1:8000',
  changeOrigin: true,
  pathFilter: '/api/v1/',
  timeout: API_TIMEOUT_MS,
  proxyTimeout: API_TIMEOUT_MS,
});
app.use(apiProxy as any);

// For `npm run dev`: the backend is started here, its logs inherited - they
// are the only view into pipeline and assembly work. The container image
// starts it itself (docker-entrypoint.sh) and sets KAE_SPAWN_BACKEND=0, or a
// second uvicorn here would race it for port 8000.
if (process.env.KAE_SPAWN_BACKEND !== '0') {
  const backend = spawn(
    'python3',
    ['-m', 'uvicorn', 'src.api.app:app', '--host', '127.0.0.1', '--port', '8000'],
    { stdio: 'inherit', env: { ...process.env, PYTHONPATH: '.' } },
  );
  backend.on('error', (err) => {
    console.error(`The backend did not start (${err.message}); every /api/v1 call will fail.`);
  });
  backend.on('exit', (code, signal) => {
    console.error(`The backend stopped (${signal ?? `exit code ${code}`}); every /api/v1 call will fail.`);
  });
  process.on('exit', () => {
    backend.kill();
  });
}

async function startServer() {
  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true, host: '0.0.0.0', port: PORT },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('{*path}', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  const server = app.listen(PORT, '0.0.0.0', () => {
    console.log(`BookAssembler Server running on http://0.0.0.0:${PORT}`);
  });
  // The job's progress socket (/api/v1/ws/jobs/:id) is an upgrade, which no
  // middleware sees: without this the browser's handshake hung unanswered.
  // Nothing else here takes one (Vite's HMR has a port of its own).
  server.on('upgrade', (req, socket, head) => {
    if (AUTH_PASSWORD && login(req) === null) {
      socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
    } else if (req.url?.startsWith('/api/v1/')) {
      apiProxy.upgrade(req, socket as Socket, head);
    } else {
      socket.destroy();
    }
  });
}

startServer();
