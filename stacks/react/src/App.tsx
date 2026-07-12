import { useState } from 'react';
import { Button } from './components/Button';

export function App() {
  const [count, setCount] = useState(0);

  return (
    <main>
      <h1>{'{{PROJECT_NAME}}'}</h1>
      <p>Clicked {count} times</p>
      <Button label="Click me" onClick={() => setCount((c) => c + 1)} />
    </main>
  );
}
