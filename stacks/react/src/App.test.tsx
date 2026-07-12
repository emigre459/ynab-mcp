import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('App', () => {
  it('increments the click counter when the button is pressed', async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByText('Clicked 0 times')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Click me' }));
    expect(screen.getByText('Clicked 1 times')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Click me' }));
    expect(screen.getByText('Clicked 2 times')).toBeInTheDocument();
  });
});
