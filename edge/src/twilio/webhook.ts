import type { FastifyInstance } from 'fastify';
import type { Settings } from '../settings.js';
import twilio from 'twilio';
import { buildRejectTwiml, buildTwiml, verticalForNumber } from './routing.js';
import { registerTwilioMediaStream } from './media-stream.js';
import { getCoreClient } from '../core-client/index.js';
import { log } from '../logging.js';

interface TwilioVoiceForm {
  Called?: string;
  CalledNumber?: string;
  From?: string;
  To?: string;
  CallSid?: string;
}

export function registerTwilioRoutes(app: FastifyInstance, settings: Settings): void {
  // Make the core client reachable from media-stream.ts.
  (app as unknown as { _core: ReturnType<typeof getCoreClient> })._core = getCoreClient(settings);
  registerTwilioMediaStream(app, settings);

  app.post('/twilio/voice', async (request, reply) => {
    const headers = request.headers;
    const form = (request.body ?? {}) as TwilioVoiceForm;

    if (settings.twilioAuthToken) {
      const signature = String(headers['x-twilio-signature'] ?? '');
      const url = `${settings.publicBaseUrl}/twilio/voice`;
      const valid = twilio.validateRequest(
        settings.twilioAuthToken,
        signature,
        url,
        form as Record<string, string>,
      );
      if (!valid) {
        log.warn({ url, signature }, 'twilio_signature_invalid');
        reply.code(403);
        return 'invalid signature';
      }
    }

    const calledNumber = (form.Called ?? form.To ?? '').trim();
    const vertical = verticalForNumber(settings, calledNumber);
    if (!vertical && Object.keys(settings.phoneVerticalMap).length > 0) {
      reply.header('content-type', 'text/xml');
      return buildRejectTwiml(
        'Sorry, this number is not configured. Please try again later.',
      );
    }

    reply.header('content-type', 'text/xml');
    return buildTwiml(settings, vertical);
  });
}
