def create_tag_type(bv, name, icon=""):
    existing = bv.get_tag_type(name)
    if existing:
        return existing
    return bv.create_tag_type(name, icon)


def tag_item(bv, addr, tag_type_name, data=""):
    # bv.add_tag() takes a tag type *name* (str); passing the TagType
    # object callers commonly hold (from create_tag_type() above) still
    # works via a deprecated compat path in the BN API, but logs a warning
    # on every call -- unwrap it here so callers can keep passing either.
    name = tag_type_name.name if hasattr(tag_type_name, "name") else tag_type_name
    bv.add_tag(addr, name, data)
