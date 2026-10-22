import type { LayerDocument } from "./types";

export type RecoveryRecord = { key: string; ownerId: string; mapKey: string; document: LayerDocument; revision: number; savedAt: string };
const DB_NAME = "splitin-map-studio";
const STORE = "recovery-v2";
const recoveryKey = (ownerId: string, mapKey: string) => `${ownerId}:${mapKey}`;
function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 2);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
}
export async function saveRecovery(record: Omit<RecoveryRecord, "key">): Promise<void> {
  if (!("indexedDB" in window)) return;
  const db = await openDb(); const value: RecoveryRecord = { ...record, key: recoveryKey(record.ownerId, record.mapKey) }; await new Promise<void>((resolve, reject) => { const request = db.transaction(STORE, "readwrite").objectStore(STORE).put(value); request.onsuccess = () => resolve(); request.onerror = () => reject(request.error); }); db.close();
}
export async function readRecovery(ownerId: string, mapKey: string): Promise<RecoveryRecord | null> {
  if (!("indexedDB" in window)) return null;
  const db = await openDb(); const value = await new Promise<RecoveryRecord | undefined>((resolve, reject) => { const request = db.transaction(STORE, "readonly").objectStore(STORE).get(recoveryKey(ownerId, mapKey)); request.onsuccess = () => resolve(request.result as RecoveryRecord | undefined); request.onerror = () => reject(request.error); }); db.close(); return value ?? null;
}
export async function clearRecovery(ownerId: string, mapKey: string): Promise<void> {
  if (!("indexedDB" in window)) return;
  const db = await openDb(); await new Promise<void>((resolve, reject) => { const request = db.transaction(STORE, "readwrite").objectStore(STORE).delete(recoveryKey(ownerId, mapKey)); request.onsuccess = () => resolve(); request.onerror = () => reject(request.error); }); db.close();
}
export async function clearAllRecovery(ownerId: string): Promise<void> {
  if (!("indexedDB" in window)) return;
  const db = await openDb(); await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(STORE, "readwrite"); const store = transaction.objectStore(STORE); const request = store.openCursor();
    request.onsuccess = () => { const cursor = request.result; if (!cursor) return; const value = cursor.value as RecoveryRecord; if (value.ownerId === ownerId) cursor.delete(); cursor.continue(); };
    transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
  }); db.close();
}
