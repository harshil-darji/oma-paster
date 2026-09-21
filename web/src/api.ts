export async function api<T = any>(path: string, body?: unknown, method = "POST"): Promise<T> {
  try {
    const res = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return await res.json();
  } catch {
    return { ok: false, error: "Lost connection to the oma-paster server." } as T;
  }
}
export const get = <T = any>(path: string) => api<T>(path, undefined, "GET");
