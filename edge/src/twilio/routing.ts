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

function escapeXml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}
