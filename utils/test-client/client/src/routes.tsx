import { createBrowserRouter, Navigate } from 'react-router';
import { AppLayout } from './components/AppLayout';
import { ConnectionPage } from './pages/ConnectionPage';
import { ApiPage } from './pages/ApiPage';
import { McpPage } from './pages/McpPage';
import { HistoryPage } from './pages/HistoryPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/connection" replace /> },
      { path: 'connection', element: <ConnectionPage /> },
      { path: 'api', element: <ApiPage /> },
      { path: 'mcp', element: <McpPage /> },
      { path: 'history', element: <HistoryPage /> },
    ],
  },
]);
