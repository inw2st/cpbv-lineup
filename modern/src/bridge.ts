type Reply<T> = { ok: boolean; data: T; error?: string };
declare global {
  interface Window {
    pywebview?: {
      api: Record<string, (...args: unknown[]) => Promise<Reply<unknown>>>;
    };
  }
}
export async function api<T>(name: string, ...args: unknown[]): Promise<T> {
  const bridge = window.pywebview?.api;
  if (!bridge)
    throw new Error(
      "데스크톱 엔진에 연결되지 않았습니다. 새 UI 실행 파일로 열어 주세요.",
    );
  const reply = (await bridge[name](...args)) as Reply<T>;
  if (!reply.ok) throw new Error(reply.error || "작업을 완료하지 못했습니다.");
  return reply.data;
}
export function ready(): Promise<void> {
  if (window.pywebview?.api) return Promise.resolve();
  return new Promise((resolve) =>
    window.addEventListener("pywebviewready", () => resolve(), { once: true }),
  );
}
