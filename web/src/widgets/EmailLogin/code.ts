// Code from the e-mail: digits only, at most 6 (pasting "123 456" or "код: 123456" works too)

export const CODE_LENGTH = 6;

export const codeDigits = (s: string) => s.replace(/\D/g, "").slice(0, CODE_LENGTH);

// Seconds until resending is allowed (at least 0)
export const secondsLeft = (until: number, now: number) => Math.max(0, Math.ceil((until - now) / 1000));
