"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { SettingsSection } from "./settings-dialog";

type Listener = () => void;

type SettingsDialogState = {
  open: boolean;
  section: SettingsSection;
  memoryOnly: boolean;
};

const listeners = new Set<Listener>();

let state: SettingsDialogState = {
  open: false,
  section: "appearance",
  memoryOnly: false,
};

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function setState(next: SettingsDialogState) {
  if (
    next.open === state.open &&
    next.section === state.section &&
    next.memoryOnly === state.memoryOnly
  ) {
    return;
  }
  state = next;
  emitChange();
}

export function subscribeSettingsDialog(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSettingsDialogSnapshot(): SettingsDialogState {
  return state;
}

const SERVER_SNAPSHOT: SettingsDialogState = {
  open: false,
  section: "appearance",
  memoryOnly: false,
};

function getServerSnapshot(): SettingsDialogState {
  return SERVER_SNAPSHOT;
}

export function openSettingsDialog(
  section: SettingsSection,
  options?: { memoryOnly?: boolean },
) {
  setState({
    open: true,
    section,
    memoryOnly: section === "memory" && options?.memoryOnly === true,
  });
}

export function setSettingsDialogOpen(open: boolean) {
  setState({ open, section: state.section, memoryOnly: state.memoryOnly });
}

/**
 * Shared open/section state for the single application-wide Settings dialog.
 *
 * Multiple entry points (nav menu, command palette, `?settings=` deep link)
 * drive this one store instead of each mounting its own `SettingsDialog`, so
 * two dialogs can never be open at once with racing per-instance flows (e.g.
 * duplicate Lark auth device-code polling).
 */
export function useSettingsDialog() {
  const snapshot = useSyncExternalStore(
    subscribeSettingsDialog,
    getSettingsDialogSnapshot,
    getServerSnapshot,
  );

  const open = useCallback(
    (section: SettingsSection, options?: { memoryOnly?: boolean }) => {
      openSettingsDialog(section, options);
    },
    [],
  );

  const setOpen = useCallback((next: boolean) => {
    setSettingsDialogOpen(next);
  }, []);

  return {
    open: snapshot.open,
    section: snapshot.section,
    memoryOnly: snapshot.memoryOnly,
    openSettings: open,
    setSettingsOpen: setOpen,
  };
}
