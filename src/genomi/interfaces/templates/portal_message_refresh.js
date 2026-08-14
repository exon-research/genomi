export function shouldReloadFrameMessages(event, state) {
  const frameId = event && event.frame_id;
  if (!frameId || !state || !state.frameId || frameId !== state.frameId) return false;
  if (state.liveMessageFrameId === frameId) return false;
  if (state.activeRun && state.activeRun.frameId === frameId) return false;
  return true;
}
