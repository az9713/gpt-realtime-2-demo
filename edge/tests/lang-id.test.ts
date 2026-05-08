import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { classifyLanguage } from '../src/voice-intent/lang-id.js';

test('detects English', () => {
  assert.strictEqual(classifyLanguage('Hello, I am calling about my AC unit'), 'en');
});

test('detects Spanish', () => {
  assert.strictEqual(classifyLanguage('Hola, gracias por su ayuda'), 'es');
});

test('detects French', () => {
  assert.strictEqual(classifyLanguage("Bonjour, j'ai besoin d'aide s'il vous plaît"), 'fr');
});

test('returns unknown for empty input', () => {
  assert.strictEqual(classifyLanguage(''), 'unknown');
});
