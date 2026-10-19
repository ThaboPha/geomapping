export default function(component) {
    const {parentElement, setStateValue} = component;
    const button = parentElement.querySelector('#locate');
    const status = parentElement.querySelector('#status');
    let disposed = false;
    let pending = false;
    let timer;
    let retry;
    let sequence = 0;

    button.onclick = () => {
        if (pending) return;
        const request = ++sequence;
        const requestId = `${Date.now()}-${Math.random()}`;
        pending = true;
        button.disabled = true;
        status.textContent = 'Finding your location…';
        let finished = false;
        let best;
        const finish = (payload) => {
            if (disposed || finished || request !== sequence) return;
            finished = true;
            pending = false;
            clearTimeout(timer);
            clearTimeout(retry);
            button.disabled = false;
            status.textContent = payload.status === 'success' ? 'Location received.' : 'Location could not be shared. You can try again.';
            setStateValue('location', {...payload, request_id: requestId});
        };
        if (!window.isSecureContext) {
            finish({status:'error', error:'insecure'});
            return;
        }
        if (!navigator.geolocation) {
            finish({status:'error', error:'unsupported'});
            return;
        }
        // This also bounds a permission prompt that is left unanswered.
        timer = setTimeout(() => finish(best || {status:'error', error:'timeout'}), 30000);
        const acquire = () => { try {
            navigator.geolocation.getCurrentPosition(
                position => {
                    if (disposed || finished || request !== sequence) return;
                    const candidate = {status:'success', latitude:position.coords.latitude,
                        longitude:position.coords.longitude, accuracy:position.coords.accuracy};
                    if (![candidate.latitude, candidate.longitude, candidate.accuracy].every(Number.isFinite) || candidate.accuracy < 0) {
                        finish({status:'error', error:'invalid'}); return;
                    }
                    if (!best || candidate.accuracy < best.accuracy) best = candidate;
                    if (best.accuracy <= 100) { finish(best); return; }
                    status.textContent = `Location is approximate (${Math.round(best.accuracy)} metres). Trying to improve it…`;
                    retry = setTimeout(acquire, 750);
                },
                error => finish(best || {status:'error', error:({1:'permission_denied',2:'unavailable',3:'timeout'})[error.code] || 'unavailable'}),
                {enableHighAccuracy:true, timeout:20000, maximumAge:0}
            );
        } catch (_) {
            finish(best || {status:'error', error:'unavailable'});
        }};
        acquire();
    };
    return () => {
        disposed = true;
        clearTimeout(timer);
        clearTimeout(retry);
        button.onclick = null;
    };
}
