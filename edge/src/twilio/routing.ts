import type { Settings } from '../settings.js';

export function verticalForNumber(settings: Settings, calledNumber: string): string | undefined {
  if (!calledNumber) return undefined;
  return settings.phoneVerticalMap[calledNumber];
}

export function buildTwiml(settings: Settings, vertical: string | undefined): string {
  const wsUrl = settings.publicBaseUrl.replace(/^http/, 'ws') + '/twilio/media-stream';
  const param = vertical
    ? `<Parameter name="vertical" value="${escapeXml(vertical)}"/>`
    : '';
  return `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="${escapeXml(wsUrl)}">
      ${param}
    </Stream>
  </Connect>
</Response>`;
}

export function buildRejectTwiml(message: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">${escapeXml(message)}</Say>
  <Hangup/>
</Response>`;
}

/**
 * Phase 4 voicemail TwiML: speak the greeting, then bridge into the
 * media-stream WebSocket with `mode=voicemail` so the edge opens a
 * whisper-only TranscriptionSession (not a RealtimeSession).
 */
export function buildVoicemailTwiml(
  settings: Settings,
  vertical: string | undefined,
  greeting: string,
): string {
  const wsUrl = settings.publicBaseUrl.replace(/^http/, 'ws') + '/twilio/media-stream';
  const verticalParam = vertical
    ? `<Parameter name="vertical" value="${escapeXml(vertical)}"/>`
    : '';
  return `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">${escapeXml(greeting)}</Say>
  <Connect>
    <Stream url="${escapeXml(wsUrl)}">
      ${verticalParam}
      <Parameter name="mode" value="voicemail"/>
    </Stream>
  </Connect>
</Response>`;
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}
