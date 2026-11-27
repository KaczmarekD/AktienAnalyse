// Zahlen aus Eingabefeldern der Depot-Seiten (D3.6): Dezimalkomma, Tausenderpunkte, leer.
import { parseAmount, toInput } from './controls';

describe('parseAmount', () => {
  it.each([
    ['12,5', '12.5'],
    ['1.500,25', '1500.25'],
    [' 10 ', '10'],
    ['0,123456', '0.123456'],
    ['2.5', '2.5'],
  ])('reads %s as %s', (text, expected) => {
    expect(parseAmount(text)).toBe(expected);
  });

  it('allows a minus only where asked, for cash in overdraft', () => {
    expect(parseAmount('-250,10', true)).toBe('-250.10');
    expect(parseAmount('-250,10')).toBeUndefined();
  });

  it('reads an empty field as null', () => {
    expect(parseAmount('  ')).toBeNull();
  });

  it.each(['zehn', '1,2,3', '-5', '1e5'])('refuses %s', (text) => {
    expect(parseAmount(text)).toBeUndefined();
  });
});

describe('toInput', () => {
  it('writes numbers of the API for a field, without trailing zeros', () => {
    expect(toInput('10.00000000')).toBe('10');
    expect(toInput('250.10')).toBe('250,1');
    expect(toInput('1500')).toBe('1500');
    expect(toInput(null)).toBe('');
  });
});
