import { RouterProvider } from 'react-router-dom';
import { router } from './routes';
import { Toaster } from './notifications/Toaster';

export function App() {
  return (
    <>
      <RouterProvider router={router} />
      <Toaster />
    </>
  );
}
