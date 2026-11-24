"use strict";
// Écran cathodique de l'atelier circuits (WebGL) : image 256×240 de la console, verre bombé, lignes de balayage,
// masque de phosphore, halo, coins sombres, neige quand il n'y a pas de signal, point blanc qui s'éteint à l'arrêt.
// Repli sur un simple canvas 2D si WebGL manque.
(function (root) {
  const VERT = `attribute vec2 p; varying vec2 uv; void main(){ uv = p * 0.5 + 0.5; uv.y = 1.0 - uv.y; gl_Position = vec4(p, 0.0, 1.0); }`;
  const FRAG = `precision mediump float;
    varying vec2 uv; uniform sampler2D img; uniform float mode, time, curve, scan, glow; uniform vec2 res;
    float rnd(vec2 c){ return fract(sin(dot(c, vec2(12.9898, 78.233)) + time * 37.0) * 43758.5453); }
    vec2 bend(vec2 c){ c = c * 2.0 - 1.0; c *= 1.0 + curve * (c.yx * c.yx) * 0.6; return c * 0.5 + 0.5; }
    void main(){
      vec2 c = bend(uv);
      if (c.x < 0.0 || c.x > 1.0 || c.y < 0.0 || c.y > 1.0) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
      vec3 col;
      if (mode < 0.5) {                       // éteint : point blanc qui s'efface
        float d = length((c - 0.5) * vec2(1.3, 1.0));
        col = vec3(1.0) * smoothstep(0.03, 0.0, d) * max(0.0, 1.0 - time * 1.5);
      } else if (mode < 1.5) {                // pas de signal : neige
        float n = rnd(floor(c * vec2(320.0, 240.0)));
        col = vec3(n * 0.85 + 0.05);
      } else {
        vec2 px = vec2(1.0 / 256.0, 0.0);
        col = texture2D(img, c).rgb;
        vec3 bloom = texture2D(img, c - px * 1.5).rgb + texture2D(img, c + px * 1.5).rgb
                   + texture2D(img, c + vec2(0.0, 1.5 / 240.0)).rgb + texture2D(img, c - vec2(0.0, 1.5 / 240.0)).rgb;
        col = col * 1.08 + bloom * 0.25 * glow * 0.25;
      }
      float line = 0.5 + 0.5 * cos(c.y * 240.0 * 6.2831853);
      float fine = clamp((res.y / 240.0 - 1.6) / 1.4, 0.0, 1.0);   // trop peu de pixels par ligne : pas de lignes (moiré)
      col *= 1.0 - scan * fine * 0.45 * (1.0 - line);
      float m = mod(floor(gl_FragCoord.x), 3.0);
      vec3 mask = m < 1.0 ? vec3(1.0, 0.82, 0.82) : m < 2.0 ? vec3(0.82, 1.0, 0.82) : vec3(0.82, 0.82, 1.0);
      col *= mix(vec3(1.0), mask, scan * 0.6);
      vec2 v = c * (1.0 - c.yx);
      col *= pow(clamp(v.x * v.y * 18.0, 0.0, 1.0), 0.28);
      gl_FragColor = vec4(pow(col, vec3(0.95)), 1.0);
    }`;

  class CRT {
    constructor(canvas, palette) {
      this.canvas = canvas;
      this.palette = palette;
      this.rgba = new Uint8Array(256 * 240 * 4);
      this.mode = 0;          // 0 éteint, 1 neige, 2 image
      this.offAt = performance.now();
      this.settings = { curve: 0.12, scan: 0.7, glow: 0.8 };
      this.gl = null;
      try { this.gl = canvas.getContext("webgl", { antialias: false, preserveDrawingBuffer: false }); } catch (error) { this.gl = null; }
      if (this.gl) this.setupGl(); else this.ctx = canvas.getContext("2d");
    }
    setupGl() {
      const gl = this.gl;
      const shader = (type, text) => { const s = gl.createShader(type); gl.shaderSource(s, text); gl.compileShader(s); return s; };
      const prog = gl.createProgram();
      gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        // un canvas qui a déjà un contexte WebGL ne peut plus donner de contexte 2D : on le remplace
        console.warn("écran cathodique : shader refusé, affichage simple", gl.getProgramInfoLog(prog));
        const fresh = this.canvas.cloneNode(false);
        this.canvas.replaceWith(fresh);
        this.canvas = fresh;
        this.gl = null; this.ctx = fresh.getContext("2d");
        return;
      }
      gl.useProgram(prog);
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, "p");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      this.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 240, 0, gl.RGBA, gl.UNSIGNED_BYTE, this.rgba);
      this.u = Object.fromEntries(["mode", "time", "curve", "scan", "glow", "res"].map((n) => [n, gl.getUniformLocation(prog, n)]));
    }
    setMode(mode) {
      if (mode === 0 && this.mode !== 0) this.offAt = performance.now();
      this.mode = mode;
    }
    // frame : Uint8Array 256×240 d'index de couleur (0-63, console 8 bits) ou Uint32Array 256×240 de points RGBA
    // déjà calculés (console 16 bits, 32 768 couleurs)
    draw(frame) {
      if (frame && this.mode === 2) {
        const out = new Uint32Array(this.rgba.buffer);
        if (frame.BYTES_PER_ELEMENT === 4) out.set(frame.subarray(0, 61440));
        else { const pal = this.palette; for (let i = 0; i < 61440; i++) out[i] = pal[frame[i]]; }
      }
      const rect = this.canvas.getBoundingClientRect();
      const w = Math.max(64, Math.round(rect.width * (window.devicePixelRatio || 1)));
      const h = Math.max(60, Math.round(rect.height * (window.devicePixelRatio || 1)));
      if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
      const t = this.mode === 0 ? (performance.now() - this.offAt) / 1000 : performance.now() / 1000 % 100;
      if (this.gl) {
        const gl = this.gl;
        gl.viewport(0, 0, w, h);
        gl.bindTexture(gl.TEXTURE_2D, this.tex);
        if (this.mode === 2) gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 256, 240, gl.RGBA, gl.UNSIGNED_BYTE, this.rgba);
        gl.uniform1f(this.u.mode, this.mode);
        gl.uniform1f(this.u.time, t);
        gl.uniform1f(this.u.curve, this.settings.curve);
        gl.uniform1f(this.u.scan, this.settings.scan);
        gl.uniform1f(this.u.glow, this.settings.glow);
        gl.uniform2f(this.u.res, w, h);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        return;
      }
      const ctx = this.ctx;
      if (!ctx) return;
      if (this.mode === 2) {
        const img = new ImageData(new Uint8ClampedArray(this.rgba.buffer.slice(0)), 256, 240);
        createImageBitmap(img).then((bmp) => { ctx.imageSmoothingEnabled = false; ctx.drawImage(bmp, 0, 0, w, h); });
      } else if (this.mode === 1) {
        const img = ctx.createImageData(w, h);
        for (let i = 0; i < img.data.length; i += 4) { const n = Math.random() * 220; img.data[i] = img.data[i + 1] = img.data[i + 2] = n; img.data[i + 3] = 255; }
        ctx.putImageData(img, 0, 0);
      } else { ctx.fillStyle = "#000"; ctx.fillRect(0, 0, w, h); }
    }
  }
  root.AetherCRT = CRT;
})(typeof window !== "undefined" ? window : globalThis);
