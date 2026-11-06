// Einmal-Passwort für neue Konten und zum Zurücksetzen (D1.4). Es entsteht im Browser aus dem
// Zufall von crypto.getRandomValues; der Server schickt nie ein Passwort zurück.

// Ohne Zeichen, die sich verwechseln lassen: I, O, l, 0, 1
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
// Größtes Vielfaches der Alphabetlänge unter 256: Bytes darüber verwerfen, sonst wären die
// ersten Zeichen häufiger
const LIMIT = 256 - (256 % ALPHABET.length);
const GROUPS = 4;
const GROUP_LENGTH = 5;

/** Vier Gruppen zu fünf Zeichen, etwa „h7Kmq-2xRtc-…“: rund 117 Bit Zufall. */
export function oneTimePassword(
  random: (bytes: Uint8Array<ArrayBuffer>) => Uint8Array<ArrayBuffer> = (bytes) =>
    crypto.getRandomValues(bytes),
): string {
  const chars: string[] = [];
  while (chars.length < GROUPS * GROUP_LENGTH) {
    for (const byte of random(new Uint8Array(new ArrayBuffer(32)))) {
      if (byte < LIMIT && chars.length < GROUPS * GROUP_LENGTH) {
        chars.push(ALPHABET[byte % ALPHABET.length]);
      }
    }
  }
  return Array.from({ length: GROUPS }, (_, i) =>
    chars.slice(i * GROUP_LENGTH, (i + 1) * GROUP_LENGTH).join(''),
  ).join('-');
}
