export interface Settings {
  port: number;
  coreHttpUrl: string;
  coreWsUrl: string;
  openaiApiKey: string;
  openaiRealtimeModel: string;
  openaiTranslateModel: string;
  openaiWhisperModel: string;
  openaiVoice: string;
  twilioAccountSid: string;
  twilioAuthToken: string;
  publicBaseUrl: string;
  phoneVerticalMap: Record<string, string>;
  logLevel: string;
}

function parsePhoneMap(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (!raw) return out;
  for (const entry of raw.split(',')) {
    const [num, vert] = entry.split('=');
    if (num && vert) out[num.trim()] = vert.trim();
  }
  return out;
}

export function loadSettings(): Settings {
  return {
    port: Number(process.env.EDGE_PORT ?? 8080),
    coreHttpUrl: process.env.CORE_HTTP_URL ?? 'http://core:8000',
    coreWsUrl: process.env.CORE_WS_URL ?? 'ws://core:8000',
    openaiApiKey: process.env.OPENAI_API_KEY ?? '',
    openaiRealtimeModel: process.env.OPENAI_REALTIME_MODEL ?? 'gpt-realtime-2',
    openaiTranslateModel: process.env.OPENAI_TRANSLATE_MODEL ?? 'gpt-realtime-translate',
    openaiWhisperModel: process.env.OPENAI_WHISPER_MODEL ?? 'gpt-realtime-whisper',
    openaiVoice: process.env.OPENAI_VOICE ?? 'alloy',
    twilioAccountSid: process.env.TWILIO_ACCOUNT_SID ?? '',
    twilioAuthToken: process.env.TWILIO_AUTH_TOKEN ?? '',
    publicBaseUrl: process.env.PUBLIC_BASE_URL ?? 'http://localhost:8080',
    phoneVerticalMap: parsePhoneMap(process.env.PHONE_VERTICAL_MAP ?? ''),
    logLevel: process.env.LOG_LEVEL ?? 'info',
  };
}
