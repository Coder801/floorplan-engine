// Project access code (service/db/access_codes.py): 8 letters and digits, shown as XXXX-XXXX.
// The input shows it in upper case, without stray characters, with a dash in the middle; pasting
// "код: abcd 2345" works too.

export const ACCESS_CODE_LENGTH = 8;

export const accessCodeChars = (s: string) => s.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, ACCESS_CODE_LENGTH);

export const formatAccessCode = (s: string) => {
  const chars = accessCodeChars(s);
  const half = ACCESS_CODE_LENGTH / 2;
  return chars.length > half ? `${chars.slice(0, half)}-${chars.slice(half)}` : chars;
};
