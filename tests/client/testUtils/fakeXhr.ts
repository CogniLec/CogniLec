// Shared fake XMLHttpRequest for tests exercising api.ts's xhrUpload()
// (docs/gaps.md #33j) -- MaterialUpload/AudioFileUpload switched from
// `fetch` to XMLHttpRequest so upload progress can be reported, so tests
// mocking `globalThis.fetch` no longer intercept those calls.

export interface FakeXhrResponse {
  status: number;
  statusText?: string;
  body?: unknown;
  progressFractions?: number[];
}

export interface FakeXhrCall {
  url: string;
  headers: Record<string, string>;
}

export function installFakeXhr(responses: FakeXhrResponse[]): {
  calls: FakeXhrCall[];
  restore: () => void;
} {
  const original = globalThis.XMLHttpRequest;
  const calls: FakeXhrCall[] = [];
  let index = 0;

  class FakeXHR {
    upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    status = 0;
    statusText = "";
    responseText = "";
    private url = "";
    private headers: Record<string, string> = {};

    open(_method: string, url: string): void {
      this.url = url;
    }

    setRequestHeader(name: string, value: string): void {
      this.headers[name] = value;
    }

    send(_body: unknown): void {
      const response = responses[Math.min(index, responses.length - 1)];
      index += 1;
      calls.push({ url: this.url, headers: { ...this.headers } });
      queueMicrotask(() => {
        if (response.progressFractions && this.upload.onprogress) {
          for (const fraction of response.progressFractions) {
            this.upload.onprogress({
              lengthComputable: true,
              loaded: fraction * 100,
              total: 100,
            } as ProgressEvent);
          }
        }
        this.status = response.status;
        this.statusText = response.statusText ?? "";
        this.responseText = response.body !== undefined ? JSON.stringify(response.body) : "";
        this.onload?.();
      });
    }
  }

  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXHR;

  return {
    calls,
    restore: () => {
      (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = original;
    },
  };
}
