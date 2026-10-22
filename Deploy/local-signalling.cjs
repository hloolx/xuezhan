// Local-only Pixel Streaming 2 smoke-test host. Uses Epic's UE5.8 signalling library.
// No public hosting, TURN, account system, or session allocator is provided here.
'use strict';
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const { createRequire } = require('node:module');

const infra = path.resolve(process.argv[2] || path.join(__dirname, '../Saved/PixelStreamingInfrastructure'));
const playerPort = Number(process.argv[3] || 18080);
const streamerPort = Number(process.argv[4] || 18888);
for (const port of [playerPort, streamerPort]) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Ports must be integers in 1024..65535');
}
if (playerPort === streamerPort) throw new Error('Player and streamer ports must differ');
const requireInfra = createRequire(path.join(infra, 'package.json'));
const express = requireInfra('express');
const { SignallingServer } = requireInfra('@epicgames-ps/lib-pixelstreamingsignalling-ue5.8');
const webRoot = path.join(infra, 'SignallingWebServer/www');
if (!fs.existsSync(path.join(webRoot, 'player.html'))) throw new Error('Frontend missing; run setup-streaming first');

const app = express();
app.disable('x-powered-by');
const httpServer = http.createServer(app);
const signalling = new SignallingServer({
  httpServer,
  streamerPort,
  streamerWsOptions: { host: '127.0.0.1' },
  peerOptions: { iceServers: [] },
  maxSubscribers: 1,
  playerKeepaliveTimeout: 30000
});
app.get('/health', (_req, res) => res.json({
  service: 'civwar-local-pixel-streaming',
  scope: 'loopback-only',
  streamers: signalling.streamerRegistry.streamers.map(s => ({
    id: s.streamerId, streaming: s.streaming, subscribers: s.subscribers.size
  }))
}));
app.get('/', (_req, res) => res.sendFile(path.join(webRoot, 'player.html')));
app.use(express.static(webRoot, { dotfiles: 'deny' }));
httpServer.on('error', error => { console.error(error.message); process.exit(1); });
httpServer.listen(playerPort, '127.0.0.1', () => {
  console.log(`CivWar browser: http://127.0.0.1:${playerPort}/`);
  console.log(`CivWar streamer: ws://127.0.0.1:${streamerPort}/`);
  console.log('One browser control slot. Both listeners are loopback-only. Ctrl+C stops this service.');
});
