function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function nestedString(value: unknown, path: string[]): string | null {
  let current: unknown = value;
  for (const key of path) {
    const next = record(current);
    if (!next || !(key in next)) return null;
    current = next[key];
  }
  return typeof current === "string" && current ? current : null;
}

export function extractCircleTransactionId(value: unknown): string | null {
  return (
    nestedString(value, ["data", "transaction", "id"]) ??
    nestedString(value, ["data", "transaction", "transactionId"]) ??
    nestedString(value, ["transaction", "id"]) ??
    nestedString(value, ["transaction", "transactionId"]) ??
    nestedString(value, ["result", "data", "transaction", "id"]) ??
    nestedString(value, ["result", "transaction", "id"]) ??
    nestedString(value, ["result", "transactionId"]) ??
    nestedString(value, ["data", "transactionId"]) ??
    nestedString(value, ["transactionId"]) ??
    null
  );
}

export function circleErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string") return error;
  const message =
    nestedString(error, ["message"]) ??
    nestedString(error, ["error", "message"]) ??
    nestedString(error, ["data", "message"]);
  return message ?? "Circle wallet request failed.";
}