const ALLOWED_ORIGIN = 'https://qkaTlehdrnf.github.io';
const ALLOWED_ORIGIN_LC = ALLOWED_ORIGIN.toLowerCase();

function corsHeaders(origin) {
  const lc = (origin || '').toLowerCase();
  const ok = lc === ALLOWED_ORIGIN_LC || lc.startsWith('http://localhost');
  return {
    'Access-Control-Allow-Origin': ok ? origin : ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const headers = corsHeaders(origin);
    const { pathname } = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers });
    }

    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';

    if (request.method === 'GET' && pathname === '/votes') {
      const [votesRaw, myVotesRaw] = await Promise.all([
        env.VOTES.get('votes'),
        env.VOTES.get(`ip:${ip}`),
      ]);
      const votes = JSON.parse(votesRaw || '{}');
      const myVotes = JSON.parse(myVotesRaw || '[]');
      return Response.json({ ...votes, my_votes: myVotes }, { headers });
    }

    if (request.method === 'POST' && pathname === '/vote') {
      let photo, action;
      try {
        ({ photo, action } = await request.json());
        if (!photo || (action !== 'up' && action !== 'down')) throw new Error();
      } catch {
        return new Response('Bad Request', { status: 400, headers });
      }

      const ipKey = `ip:${ip}`;
      const [votesRaw, myVotesRaw] = await Promise.all([
        env.VOTES.get('votes'),
        env.VOTES.get(ipKey),
      ]);
      const votes = JSON.parse(votesRaw || '{}');
      let myVotes = JSON.parse(myVotesRaw || '[]');
      const has = myVotes.includes(photo);

      if (action === 'up') {
        if (!has) {
          votes[photo] = { up: (votes[photo]?.up || 0) + 1 };
          myVotes.push(photo);
        }
      } else { // 'down' — cancel a previous heart
        if (has) {
          const next = (votes[photo]?.up || 0) - 1;
          if (next > 0) votes[photo] = { up: next };
          else delete votes[photo];
          myVotes = myVotes.filter(p => p !== photo);
        }
      }

      await Promise.all([
        env.VOTES.put('votes', JSON.stringify(votes)),
        env.VOTES.put(ipKey, JSON.stringify(myVotes)),
      ]);

      return Response.json({ up: votes[photo]?.up || 0, voted: action === 'up' }, { headers });
    }

    return new Response('Not Found', { status: 404, headers });
  },
};
