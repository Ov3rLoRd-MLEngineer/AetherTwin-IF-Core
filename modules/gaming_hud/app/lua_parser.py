"""
Mini-parseur de tables Lua (format écrit par WoW dans les SavedVariables)
"""
import re


# ===========================================================================
#  Mini-parseur de tables Lua (format écrit par WoW dans les SavedVariables)
# ===========================================================================
class LuaParseError(Exception):
    pass


_NUMBER = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_STOP_DOUBLE = re.compile(r'["\\\\]')
_STOP_SINGLE = re.compile(r"['\\\\]")
_ESCAPES = {'n': 10, 'r': 13, 't': 9, '\\': 92, '"': 34, "'": 39,
            'a': 7, 'b': 8, 'f': 12, 'v': 11}


class _LuaParser:
    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)

    def _skip(self):
        while self.i < self.n:
            c = self.s[self.i]
            if c.isspace():
                self.i += 1
            elif self.s.startswith('--', self.i):
                j = self.s.find('\n', self.i)
                self.i = self.n if j == -1 else j + 1
            else:
                break

    def _expect(self, ch):
        self._skip()
        if self.i >= self.n or self.s[self.i] != ch:
            raise LuaParseError(f"'{ch}' attendu à la position {self.i}")
        self.i += 1

    def parse_file(self):
        """Retourne {nom_variable: valeur} pour toutes les affectations de premier niveau."""
        result = {}
        while True:
            self._skip()
            if self.i >= self.n:
                break
            m = _IDENT.match(self.s, self.i)
            if not m:
                break
            self.i = m.end()
            self._skip()
            if self.i >= self.n or self.s[self.i] != '=':
                break
            self.i += 1
            result[m.group()] = self._value()
        return result

    def _value(self):
        self._skip()
        if self.i >= self.n:
            raise LuaParseError("fin de fichier inattendue")
        c = self.s[self.i]
        if c == '{':
            return self._table()
        if c in '"\'':
            return self._string()
        m = _NUMBER.match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group()
            return float(t) if any(x in t for x in '.eE') else int(t)
        m = _IDENT.match(self.s, self.i)
        if m:
            self.i = m.end()
            return {'true': True, 'false': False, 'nil': None}.get(m.group(), m.group())
        raise LuaParseError(f"valeur inattendue à la position {self.i}")

    def _string(self):
        quote = self.s[self.i]
        self.i += 1
        stop = _STOP_DOUBLE if quote == '"' else _STOP_SINGLE
        parts, pending = [], bytearray()   # pending : octets issus d'échappements décimaux (\\ddd), décodés ensemble

        def flush():
            if pending:
                parts.append(pending.decode("utf-8", "replace"))
                pending.clear()

        while self.i < self.n:
            m = stop.search(self.s, self.i)
            if not m:
                break
            j = m.start()
            if j > self.i:                       # tronçon sans caractère spécial : copié d'un bloc (rapide)
                flush()
                parts.append(self.s[self.i:j])
            self.i = j
            c = self.s[j]
            if c == quote:
                self.i += 1
                flush()
                return "".join(parts)
            # antislash
            self.i += 1
            c = self.s[self.i]
            if c.isdigit():
                k = self.i
                while k < self.n and k < self.i + 3 and self.s[k].isdigit():
                    k += 1
                pending.append(int(self.s[self.i:k]) & 0xFF)
                self.i = k
                continue
            flush()
            if c in _ESCAPES:
                parts.append(chr(_ESCAPES[c]))
            elif c == "\n":
                parts.append("\n")
            else:
                parts.append(c)
            self.i += 1
        raise LuaParseError("chaîne non terminée")

    def _table(self):
        self.i += 1  # '{'
        result = {}
        position = 1
        while True:
            self._skip()
            if self.i >= self.n:
                raise LuaParseError("table non fermée")
            c = self.s[self.i]
            if c == '}':
                self.i += 1
                return result
            if c in ',;':
                self.i += 1
                continue
            if c == '[':
                self.i += 1
                key = self._value()
                self._expect(']')
                self._expect('=')
                result[key] = self._value()
                continue
            m = _IDENT.match(self.s, self.i)
            if m:
                save = self.i
                self.i = m.end()
                self._skip()
                if (self.i < self.n and self.s[self.i] == '='
                        and not self.s.startswith('==', self.i)):
                    self.i += 1
                    result[m.group()] = self._value()
                    continue
                self.i = save
            result[position] = self._value()
            position += 1


def parse_lua_file(content):
    """Parse le contenu d'un fichier SavedVariables en dict Python."""
    return _LuaParser(content.lstrip('\ufeff')).parse_file()
