const API_BASE = '';
const DEFAULT_TIMEOUT = 30000;

export class ApiError extends Error {
  constructor(message, { kind = 'http', status = 0, retryable = false } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.retryable = retryable;
  }
}

export async function request(path, options = {}) {
  const {
    method = 'GET',
    body = null,
    headers = {},
    timeout = DEFAULT_TIMEOUT,
    retries = 0,
    signal = null,
  } = options;

  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const onAbort = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener('abort', onAbort, { once: true });

    try {
      const response = await fetch(API_BASE + path, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: body == null ? null : JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const payload = await response.json();
          const detail = payload.detail || payload.error || payload.message;
          message = typeof detail === 'string' ? detail : JSON.stringify(detail);
        } catch {
          // 保留状态码错误。
        }
        throw new ApiError(message, {
          status: response.status,
          retryable: response.status >= 500,
        });
      }

      if (response.status === 204) return null;
      return await response.json();
    } catch (error) {
      if (error instanceof ApiError) {
        lastError = error;
      } else if (error.name === 'AbortError') {
        lastError = new ApiError('请求已取消或超时', { kind: 'abort' });
      } else {
        lastError = new ApiError('网络异常，请检查服务是否启动', {
          kind: 'network',
          retryable: true,
        });
      }

      if (attempt < retries && lastError.retryable) {
        await new Promise(resolve => setTimeout(resolve, 400 * 2 ** attempt));
        continue;
      }
      throw lastError;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }
  throw lastError;
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}
