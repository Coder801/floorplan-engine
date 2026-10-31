// Код из письма: только цифры, не больше 6 (вставка «123 456» или «код: 123456» — тоже)

export const CODE_LENGTH = 6;

export const codeDigits = (s: string) => s.replace(/\D/g, "").slice(0, CODE_LENGTH);

// Секунд до повторной отправки (не меньше 0)
export const secondsLeft = (until: number, now: number) => Math.max(0, Math.ceil((until - now) / 1000));
