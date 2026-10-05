"""Decode React Router v7 single-fetch (turbo-stream v2) hydration payloads embedded in SSR HTML."""
import json, re

HOLE, NAN, NEG_INF, NEG_ZERO, NULL, POS_INF, UNDEF = -1, -2, -3, -4, -5, -6, -7

def extract_chunks(html):
    return re.findall(r'__reactRouterContext\.streamController\.enqueue\((".*?")\);</script>', html, re.S)

def decode(chunk_json_string):
    arr = json.loads(json.loads(chunk_json_string))
    cache = {}
    def hydrate(idx):
        if idx in cache: return cache[idx]
        if idx < 0:
            return {NULL: None, UNDEF: None, NAN: float('nan'), POS_INF: float('inf'), NEG_INF: float('-inf'), NEG_ZERO: 0.0, HOLE: None}[idx]
        v = arr[idx]
        if isinstance(v, (str, int, float, bool)) or v is None:
            cache[idx] = v; return v
        if isinstance(v, list):
            if v and isinstance(v[0], str):
                tag = v[0]
                if tag == 'D': r = v[1]
                elif tag in ('M',): r = {hydrate(v[i]): hydrate(v[i+1]) for i in range(1, len(v), 2)}
                elif tag in ('S',): r = [hydrate(x) for x in v[1:]]
                elif tag in ('N', 'O'): r = hydrate(v[1]) if len(v) > 1 else {}
                elif tag == 'P': r = hydrate(v[1]) if len(v) > 1 else None
                elif tag == 'E': r = {'error': v[1:]}
                elif tag == 'R': r = v[1]
                elif tag == 'B': r = v[1]
                elif tag == 'Y': r = v[1]
                else: r = [hydrate(x) for x in v]
                cache[idx] = r; return r
            r = []; cache[idx] = r
            for x in v: r.append(hydrate(x))
            return r
        if isinstance(v, dict):
            r = {}; cache[idx] = r
            for k, val in v.items():
                key = hydrate(int(k[1:])) if k.startswith('_') else k
                r[key] = hydrate(val)
            return r
        return v
    return hydrate(0)

def loader_data(html):
    chunks = extract_chunks(html)
    if not chunks: return None
    root = decode(chunks[0])
    return root.get('loaderData') if isinstance(root, dict) else root

if __name__ == '__main__':
    import sys
    ld = loader_data(open(sys.argv[1]).read())
    print(json.dumps(ld, indent=1)[:3000] if len(sys.argv) < 3 else json.dumps(ld))
