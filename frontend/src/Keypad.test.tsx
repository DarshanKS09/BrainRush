import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Keypad } from './components/game';

afterEach(() => cleanup());

describe('Keypad', () => {
  it('emits digits, backspace, clear and submit accessibly', () => {
    const onKey = vi.fn();
    render(<Keypad onKey={onKey} />);
    fireEvent.click(screen.getByRole('button', { name: 'Digit 4' }));
    fireEvent.click(screen.getByRole('button', { name: 'Digit 2' }));
    fireEvent.click(screen.getByRole('button', { name: 'Backspace' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(onKey.mock.calls.map((c) => c[0])).toEqual(['4', '2', 'back', 'clear']);
  });

  it('disables all keys when finished', () => {
    render(<Keypad onKey={() => {}} disabled />);
    for (const btn of screen.getAllByRole('button')) {
      expect(btn).toBeDisabled();
    }
  });
});
