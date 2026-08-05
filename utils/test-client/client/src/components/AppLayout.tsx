import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';
import {
  Page,
  Masthead,
  MastheadMain,
  MastheadBrand,
  MastheadContent,
  Nav,
  NavList,
  NavItem,
  PageSidebar,
  PageSidebarBody,
  PageSection,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  TextInput,
  Button,
} from '@patternfly/react-core';
import { ConnectionBadge } from './ConnectionBadge';
import { SimulationBadge } from './SimulationBadge';
import { useConnectionStore } from '../state/useConnectionStore';
import { useSimulationStore } from '../state/useSimulationStore';
import { health } from '../api/harness';
import { useNotifications } from '../notifications/useNotifications';

const NAV = [
  { to: '/connection', label: 'Connection' },
  { to: '/api', label: 'API' },
  { to: '/mcp', label: 'MCP' },
  { to: '/history', label: 'History' },
];

export function AppLayout() {
  const location = useLocation();
  const {
    harnessUrl,
    connected,
    lastHealthMs,
    connectionError,
    setHarnessUrl,
    setConnected,
    setFailed,
  } = useConnectionStore();
  const sim = useSimulationStore();
  const [testing, setTesting] = useState(false);

  const testConnection = async () => {
    setTesting(true);
    try {
      const res = await health();
      setConnected(res.durationMs);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setFailed(message);
      useNotifications.getState().notify('danger', `Connection failed: ${message}`);
    } finally {
      setTesting(false);
    }
  };

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>Harness Test Client</MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar isFullHeight isStatic>
          <ToolbarContent>
            <ToolbarItem>
              <TextInput
                aria-label="Harness URL"
                value={harnessUrl}
                onChange={(_e, v) => setHarnessUrl(v)}
                style={{ minWidth: '16rem' }}
              />
            </ToolbarItem>
            <ToolbarItem>
              <Button variant="secondary" isLoading={testing} onClick={testConnection}>
                Test connection
              </Button>
            </ToolbarItem>
            <ToolbarItem>
              <ConnectionBadge
                connected={connected}
                lastHealthMs={lastHealthMs}
                error={connectionError}
              />
            </ToolbarItem>
            <ToolbarItem>
              <SimulationBadge name={sim.name} status={sim.status} />
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );

  const sidebar = (
    <PageSidebar>
      <PageSidebarBody>
        <Nav>
          <NavList>
            {NAV.map((item) => (
              <NavItem key={item.to} isActive={location.pathname === item.to}>
                <NavLink to={item.to}>{item.label}</NavLink>
              </NavItem>
            ))}
          </NavList>
        </Nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page masthead={masthead} sidebar={sidebar}>
      <PageSection>
        <Outlet />
      </PageSection>
    </Page>
  );
}
