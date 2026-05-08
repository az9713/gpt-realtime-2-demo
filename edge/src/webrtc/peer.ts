/**
 * Placeholder for an SDP offer/answer pipeline. v1 browser audio runs
 * over the same WebSocket as control via base64 PCM frames; full WebRTC
 * with DTLS-SRTP is reserved for a future iteration. The shape below
 * documents the seam where a true peer-connection bridge will plug in.
 */
export interface PeerConnectionBridge {
  open(remoteSdp: string): Promise<string>;
  close(): Promise<void>;
}

export const createPeerConnectionBridge = (): PeerConnectionBridge => ({
  open: async () => {
    throw new Error('full WebRTC peer connection bridge not implemented in v1');
  },
  close: async () => {
    /* noop */
  },
});
