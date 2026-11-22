// The server's clock as seen from the browser. Positions are computed for the server's moment, which may be a
// replay of the past or a fixed moment, so the browser keeps an offset (or a frozen time) from each update
export class ServerClock {
  private offsetMs = 0;
  private frozenAt: number | null = null;
  private known = false;

  /** Call with each payload's `at` and `clock`. */
  update(at: string, clock: string, receivedAt: number = Date.now()) {
    const serverMs = Date.parse(at);
    if (clock.startsWith("fixed")) {
      this.frozenAt = serverMs;
    } else {
      this.frozenAt = null;
      const offset = serverMs - receivedAt;
      // Ignore network jitter, so trains don't twitch when an update lands a little early or late
      if (!this.known || Math.abs(offset - this.offsetMs) > 2000) this.offsetMs = offset;
    }
    this.known = true;
  }

  now(clientMs: number = Date.now()): number {
    return this.frozenAt ?? clientMs + this.offsetMs;
  }

  get ready(): boolean {
    return this.known;
  }
}
