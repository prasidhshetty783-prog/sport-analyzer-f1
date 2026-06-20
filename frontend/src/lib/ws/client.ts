// Reconnecting WebSocket client speaking the generated protocol types.
import type { ClientMessage, ServerMessage } from "./types";

export type ConnStatus = "connecting" | "open" | "closed";

export class RaceSocket {
  private ws: WebSocket | null = null;
  private retry = 0;
  private closedByUs = false;

  constructor(
    private url: string,
    private onMessage: (m: ServerMessage) => void,
    private onStatus: (s: ConnStatus) => void,
  ) {}

  connect(): void {
    this.closedByUs = false;
    this.onStatus("connecting");
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.retry = 0;
      this.onStatus("open");
    };
    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as ServerMessage;
        if (msg && typeof msg === "object" && "kind" in msg) this.onMessage(msg);
      } catch {
        /* tolerate malformed frames */
      }
    };
    this.ws.onclose = () => {
      this.onStatus("closed");
      if (!this.closedByUs) {
        const delay = Math.min(500 * 2 ** this.retry++, 8000);
        setTimeout(() => this.connect(), delay);
      }
    };
    this.ws.onerror = () => this.ws?.close();
  }

  send(cmd: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmd));
    }
  }

  close(): void {
    this.closedByUs = true;
    this.ws?.close();
  }
}
