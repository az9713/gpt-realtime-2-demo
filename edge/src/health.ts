import type { FastifyInstance } from 'fastify';
import type { Settings } from './settings.js';
import { request } from 'undici';

export function registerHealth(app: FastifyInstance, settings: Settings): void {
  app.get('/healthz', async () => {
    let coreOk = false;
    try {
      const res = await request(`${settings.coreHttpUrl}/healthz`, { method: 'GET' });
      coreOk = res.statusCode === 200;
      await res.body.dump();
    } catch {
      coreOk = false;
    }
    return {
      status: coreOk ? 'ok' : 'degraded',
      core: coreOk ? 'ok' : 'unreachable',
    };
  });
}
