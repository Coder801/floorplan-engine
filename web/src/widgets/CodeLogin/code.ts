// Код доступа к проекту (service/db/access_codes.py): 8 букв и цифр, показывается как XXXX-XXXX.
// В поле ввода — заглавными, без лишних знаков, с дефисом посередине; вставка «код: abcd 2345» —
// тоже.

export const ACCESS_CODE_LENGTH = 8;

export const accessCodeChars = (s: string) => s.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, ACCESS_CODE_LENGTH);

export const formatAccessCode = (s: string) => {
  const chars = accessCodeChars(s);
  const half = ACCESS_CODE_LENGTH / 2;
  return chars.length > half ? `${chars.slice(0, half)}-${chars.slice(half)}` : chars;
};
