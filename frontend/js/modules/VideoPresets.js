/** Capture intent: dimensions are negotiated on the server, never guessed from enumeration. */
export function captureOptions(deviceId, profile = 'digital', standard = 'ntsc') {
    return {device_id: Number(deviceId), profile, standard};
}

export function defaultAspect(profile) {
    return profile === 'analog' ? '4:3' : 'native';
}
