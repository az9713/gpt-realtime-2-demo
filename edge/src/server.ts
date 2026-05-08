import Fastify from 'fastify';
import websocket from '@fastify/websocket';
import formbody from '@fastify/formbody';
import { loadSettings } from './settings.js';
import { log } from './logging.js';
import { registerWebRtcSignaling } from './webrtc/signaling.js';
import { registerTwilioRoutes } from './twilio/webhook.js';
import { registerCoreClient } from './core-client/index.js';
import { registerHealth } from './health.js';

const settings = loadSettings();

const fastify = Fastify({
  logger: { level: settings.logLevel },
  bodyLimit: 5 * 1024 * 1024,
});

await fastify.register(websocket, {
  options: { maxPayload: 1024 * 1024 },
});
await fastify.register(formbody);

registerHealth(fastify, settings);
registerCoreClient(fastify, settings);
registerWebRtcSignaling(fastify, settings);
registerTwilioRoutes(fastify, settings);

const start = async (): Promise<void> => {
  try {
    await fastify.listen({ host: '0.0.0.0', port: settings.port });
    log.info({ port: settings.port }, 'edge_listening');
  } catch (err) {
    log.error({ err }, 'edge_listen_failed');
    process.exit(1);
  }
};

void start();
