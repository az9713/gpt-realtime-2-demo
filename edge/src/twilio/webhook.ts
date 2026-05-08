import type { FastifyInstance } from 'fastify';
import type { Settings } from '../settings.js';
import { request as undiciRequest } from 'undici';
import twilio from 'twilio';
import {
  buildRejectTwiml,
  buildTwiml,
  buildVoicemailTwiml,
  verticalForNumber,
} from './routing.js';
import { registerTwilioMediaStream } from './media-stream.js';
import { getCoreClient } from '../core-client/index.js';
import { log } from '../logging.js';

interface BusinessStatus {
  vertical: string;
  open: boolean;
  voicemail_greeting: string | null;
  supports_voicemail: boolean;
}

/**
 * Asks the core's /v1/verticals/{name}/business-status endpoint whether
 * the vertical is open right now and (if not) what greeting to play.
 * Failures are treated as "open" — the agent serves the call as normal,
 * never silently dropping inbound traffic.
 */
async function fetchBusinessStatus(
  settings: Settings,
  vertical: string,
): Promise<BusinessStatus | null> {
  try {
    const res = await undiciRequest(
      `${settings.coreHttpUrl}/v1/verticals/${encodeURIComponent(vertical)}/business-status`,
      { method: 'GET' },
    );
    if (res.statusCode >= 400) {
      await res.body.dump();
      return null;
    }
    return (await res.body.json()) as BusinessStatus;
  } catch (err) {
    log.warn({ err, vertical }, 'business_status_fetch_failed');
    return null;
  }
}

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

    // If the vertical defines business hours and we're outside them,
    // serve the voicemail TwiML instead of the agent TwiML.
    if (vertical) {
      const status = await fetchBusinessStatus(settings, vertical);
      if (status && status.supports_voicemail && !status.open) {
        const greeting =
          status.voicemail_greeting ??
          'You have reached the after-hours line. Please leave a message after the tone.';
        return buildVoicemailTwiml(settings, vertical, greeting);
      }
    }

    return buildTwiml(settings, vertical);
  });
}
