// static server with COOP/COEP (for multi-thread wasm). usage: node serve.mjs <root> <port>
import http from 'http'; import fs from 'fs'; import path from 'path';
const root = path.resolve(process.argv[2]), port = +process.argv[3] || 8765;
const mime = { '.js':'text/javascript','.mjs':'text/javascript','.html':'text/html','.wasm':'application/wasm','.json':'application/json' };
http.createServer((q, r) => {
  const f = path.join(root, decodeURIComponent(q.url.split('?')[0]));
  if (!f.startsWith(root) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.writeHead(404); return r.end(); }
  const st = fs.statSync(f);
  r.writeHead(200, { 'content-type': mime[path.extname(f)] || 'application/octet-stream', 'content-length': st.size,
    'cross-origin-opener-policy': 'same-origin', 'cross-origin-embedder-policy': 'require-corp', 'cross-origin-resource-policy': 'same-origin' });
  fs.createReadStream(f).pipe(r);
}).listen(port, () => console.log('serving', root, port));
