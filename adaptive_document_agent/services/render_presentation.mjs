// Trusted local helper. Arguments are paths, never executable document content.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import http2 from 'node:http2';
import { syncBuiltinESMExports } from 'node:module';

// Rendering is offline in every execution mode. Neither document resources nor
// renderer dependencies may open a network connection through Node transports.
const offline = () => { throw new Error('Network access disabled in PPT renderer'); };
http.get = http.request = https.get = https.request = offline;
net.connect = net.createConnection = tls.connect = dgram.createSocket = http2.connect = offline;
net.Socket.prototype.connect = offline;
globalThis.fetch = offline;
globalThis.WebSocket = offline;
syncBuiltinESMExports();

try {
  const [modulePath, source, output] = process.argv.slice(2);
  const { FileBlob, PresentationFile } = await import(pathToFileURL(modulePath).href);
  const deck = await PresentationFile.importPptx(await FileBlob.load(source));
  if (!deck.slides.items.length || deck.slides.items.length > 150) throw new Error('Page limit');
  for (const [index, slide] of deck.slides.items.entries()) {
    const layout = await slide.export({format: 'layout'});
    const data = JSON.parse(await layout.text());
    const frame = data.slide?.frame;
    if (!frame || frame.width * frame.height > 8000000) throw new Error('Pixel limit');
    const png = await deck.export({slide, format: 'png', scale: 1});
    await fs.writeFile(path.join(output, `slide-${index + 1}.png`), new Uint8Array(await png.arrayBuffer()));
    await fs.writeFile(path.join(output, `slide-${index + 1}.json`), JSON.stringify(data));
  }
  const inputSha256 = createHash('sha256').update(await fs.readFile(source)).digest('hex');
  await fs.writeFile(path.join(output, 'complete.tmp'), JSON.stringify({complete: true, pages: deck.slides.items.length, inputSha256}));
  await fs.rename(path.join(output, 'complete.tmp'), path.join(output, 'complete.json'));
  // The parent owns this worker's lifetime and terminates it after this atomic
  // receipt. Some Windows native raster runtimes crash during normal teardown;
  // do not turn a crash exit code into a successful render result.
  setInterval(() => {}, 1000);
} catch {
  process.exit(1);
}
