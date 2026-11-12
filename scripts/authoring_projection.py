"""Project declared envelope entries without inventing authoring-contract fields.

These functions do not validate the kernel schema, read referenced files, expand
environment variables, or execute handlers. JSON pointers identify original
entries; callers must bind results to the original artifact bytes.
"""


class ProjectionError(ValueError):
    """The declared envelope cannot be projected without ambiguity."""


def pointer(parent, key):
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


def mapping(value, path):
    if not isinstance(value, dict):
        raise ProjectionError(f"{path or '/'}: expected an object")
    return value


def array(value, path):
    if not isinstance(value, list):
        raise ProjectionError(f"{path}: expected an array")
    return value


def lift(entry, field, value, path):
    """Envelope identity wins only when an explicit duplicate agrees exactly."""
    if field in entry and (type(entry[field]) is not type(value) or entry[field] != value):
        raise ProjectionError(f"{path}: conflicting envelope field {field}")
    entry[field] = value


def project_mcp(document, *, bare=False, base=None):
    """Return (JSON pointer, server) pairs for an explicit mcpServers map.

    Only the map key is lifted to name. In particular, type is not silently
    converted to transport and absent args/env/enablement remain absent.
    An empty map returns no targets, not a successful schema assessment.
    """
    root = mapping(document, "")
    base = ("" if bare else "/mcpServers") if base is None else base
    servers = root if bare else mapping(root.get("mcpServers"), base)
    result = []
    for name, value in servers.items():
        path = pointer(base, name)
        entry = dict(mapping(value, path))
        lift(entry, "name", name, path)
        result.append((path, entry))
    return result


def project_hooks(document, *, bare=False, base=None):
    """Return (JSON pointer, handler) pairs from explicit nested hook groups.

    Event keys and explicitly declared group matchers are lifted. No defaults or
    plugin metadata are supplied. A path-valued hooks declaration is not an
    inline envelope and is refused here; resolving references is a separate
    discovery operation. Empty maps/groups contain no measured handlers.
    """
    root = mapping(document, "")
    base = ("" if bare else "/hooks") if base is None else base
    events = root if bare else mapping(root.get("hooks"), base)
    result = []
    for event, groups in events.items():
        event_path = pointer(base, event)
        for group_index, group in enumerate(array(groups, event_path)):
            group_path = pointer(event_path, group_index)
            group = mapping(group, group_path)
            handlers_path = pointer(group_path, "hooks")
            for handler_index, handler in enumerate(array(group.get("hooks"), handlers_path)):
                path = pointer(handlers_path, handler_index)
                entry = dict(mapping(handler, path))
                lift(entry, "event", event, path)
                if "matcher" in group:
                    lift(entry, "matcher", group["matcher"], path)
                elif "matcher" in entry:
                    raise ProjectionError(f"{path}: matcher belongs to the enclosing group")
                result.append((path, entry))
    return result


def component_parts(manifest, field):
    """Retain inline objects and reference strings with their source pointers.

    Plugin hooks/mcpServers can each be one declaration or an ordered array.
    References are returned inert; discovery must separately validate containment
    and bind every referenced artifact. No URL or bundle is fetched here.
    """
    root = mapping(manifest, "")
    if field not in root:
        return []
    value = root[field]
    base = pointer("", field)
    parts = [(pointer(base, i), item) for i, item in enumerate(value)] if isinstance(value, list) else [(base, value)]
    for path, item in parts:
        if not isinstance(item, (dict, str)) or (isinstance(item, str) and not item):
            raise ProjectionError(f"{path}: expected an inline object or nonempty artifact reference")
    return parts
