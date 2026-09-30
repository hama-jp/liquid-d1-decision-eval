"""Small, serial HTTPS client. No retries. Credentials never enter records."""
import datetime
import hashlib
import http.client
import json
import math
import os
import time

MODEL = 'd1:free'
HOST = 'api.liquid.ai'
ENDPOINT = '/decisions/v1/systemone'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class Client:
    def __init__(self, timeout=10):
        self.key = os.environ.get('LIQUID_API_KEY')
        if not self.key:
            raise RuntimeError('LIQUID_API_KEY is missing; reload .bashrc')
        self.connection = None
        self.count = 0
        self.timeout = timeout

    def call(self, payload):
        started = time.perf_counter()
        cold = self.connection is None or self.connection.sock is None
        record = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'endpoint': 'https://' + HOST + ENDPOINT, 'request': payload,
                  'request_sha256': digest(payload), 'retry': False,
                  'connection_first_request': cold}
        self.count += 1
        try:
            if self.connection is None:
                self.connection = http.client.HTTPSConnection(HOST, timeout=self.timeout)
            self.connection.request('POST', ENDPOINT, body=json.dumps(payload, ensure_ascii=False).encode(),
                                    headers={'Authorization': 'Bearer ' + self.key,
                                             'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = self.connection.getresponse()
            body = response.read().decode('utf-8', errors='replace').replace(self.key, '[REDACTED]')
            record['http_status'] = response.status
            record['response_headers'] = {k.lower(): v for k, v in response.getheaders()
                                          if k.lower() in {'date', 'server-timing', 'x-request-id', 'request-id',
                                                           'retry-after', 'x-ratelimit-remaining', 'x-ratelimit-limit'}}
            record['connection_closed_by_server'] = response.will_close
            try:
                record['response'] = json.loads(body)
            except json.JSONDecodeError:
                record['response_text'] = body
        except Exception as error:
            record['error'] = type(error).__name__
            # Never silently resend a possibly completed request.
            if self.connection:
                self.connection.close()
            self.connection = None
        record['completed_monotonic'] = time.perf_counter()
        record['rtt_ms'] = (record['completed_monotonic'] - started) * 1000
        return record

    def close(self):
        if self.connection:
            self.connection.close()


def number(v):
    return type(v) in (int, float) and math.isfinite(v)


def validate(payload, response):
    """Check the documented contract; retain raw values even if validation fails."""
    errors = []
    if not isinstance(response, dict):
        return ['response_not_object']
    answers = response.get('answers')
    if not isinstance(answers, dict):
        return ['answers_not_object']
    if set(answers) != set(payload['questions']):
        errors.append('question_keys_mismatch')
    for name, question in payload['questions'].items():
        answer = answers.get(name)
        if not isinstance(answer, dict):
            errors.append(name + ':answer_missing')
            continue
        kind = question.get('type')
        if kind not in ['noul', 'choice', 'score']:
            errors.append(name + ':invalid_request_type')
            continue
        if answer.get('type') != kind:
            errors.append(name + ':type_mismatch')
        if kind == 'noul':
            p = answer.get('noul')
            if not number(p) or not 0 <= p <= 1:
                errors.append(name + ':invalid_noul')
            continue
        probs = answer.get('probabilities')
        expected = set(question['criteria']) if kind == 'choice' else {str(i) for i in range(len(question['criteria']))}
        if not isinstance(probs, dict) or set(probs) != expected:
            errors.append(name + ':probability_keys')
            continue
        if any(not number(p) or not 0 <= p <= 1 for p in probs.values()):
            errors.append(name + ':invalid_probability')
            continue
        if abs(sum(probs.values()) - 1) > 0.002:
            errors.append(name + ':probability_sum')
        c = answer.get('confidence')
        if not number(c) or not 0 <= c <= 1:
            errors.append(name + ':invalid_confidence')
        if kind == 'choice':
            choice = answer.get('choice')
            if not isinstance(choice, str) or choice not in expected:
                errors.append(name + ':unknown_choice')
            elif probs[choice] < max(probs.values()) - 0.0001:
                errors.append(name + ':choice_not_argmax')
        elif kind == 'score':
            score = answer.get('score')
            if not number(score) or not 0 <= score <= len(expected) - 1:
                errors.append(name + ':invalid_score')
            elif abs(score - sum(int(k) * p for k, p in probs.items())) > 0.005:
                errors.append(name + ':score_not_expectation')
    return errors


def evaluate(answers, gold, key_map=None):
    """No LLM judge. Every expected answer lives in the precommitted fixture."""
    mapped = {key_map.get(k, k) if key_map else k: v for k, v in answers.items()}
    result = {}
    if 'problem' in mapped:
        p = mapped['problem']['noul']
        result['problem'] = {'expected': gold['problem'], 'actual': p >= .5,
                             'correct': (p >= .5) == gold['problem'], 'p_yes': p,
                             'brier': (p - int(gold['problem'])) ** 2}
    if 'department' in mapped:
        a = mapped['department']
        result['department'] = {'expected': gold['department'], 'actual': a['choice'],
                                'correct': a['choice'] == gold['department'],
                                'p_gold': a['probabilities'][gold['department']]}
    if 'urgency' in mapped:
        a = mapped['urgency']
        modes = [int(k) for k, v in a['probabilities'].items() if v == max(a['probabilities'].values())]
        result['urgency'] = {'expected': gold['urgency'], 'modal_levels': modes,
                            'correct': modes == [gold['urgency']], 'score': a['score'],
                            'absolute_error': abs(a['score'] - gold['urgency'])}
    return result
