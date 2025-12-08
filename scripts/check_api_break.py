import subprocess
import sys
from lxml import etree

class Breakable:
    def __init__(self, index, xml_etree):
        self.index = index
        self.name = xml_etree.get("name")
        self.is_wip = xml_etree.find("wip") is not None
        self.parts = self._extract_parts(xml_etree)

    def _extract_parts(self):
        pass

    @property
    def display_type(self):
        return type(self).__name__

    def __str__(self):
        output = self.name + "["
        if self.is_wip:
            output += "WIP-"
        output += self.display_type + "](\n\t"
        output += "\n\t".join(name for name in self.parts)


class Enum(Breakable):
    def _extract_parts(self, xml_etree):
        return {
            entry.get("value"): {
                "wip": (self.is_wip or entry.find("wip") is not None),
                "name": entry.get("name"),
            }
            for entry in xml_etree.findall("entry")
        }


class Msg(Breakable):
    @property
    def display_type(self):
        return super().display_type + f"(#{self.index})"

    def _extract_parts(self, xml_etree):
        return {
            index: {
                "wip": (self.is_wip or field.find("wip") is not None),
                "name": field.get("name")
            }
            for index, field in enumerate(xml_etree.findall("field"))
        }


class Delta:
    def __init__(self, old: Breakable, new: Breakable):
        self.api_break = False
        self.name = old.name + "["
        if old.is_wip:
            self.name += "WIP-"
        self.name += old.display_type + "]"
        
        # Handle component renames
        if new.name != old.name:
            self.name += "->" + new.name
            if not old.is_wip:
                self.api_break = True

        self.parts = []
        if old.parts != new.parts:
            old_id_sequence = iter(old.parts)
            new_id_sequence = iter(new.parts)
            # Assume there's always at least one part
            new_id = next(new_id_sequence)
            new_part = new.parts[new_id]
            old_id = next(old_id_sequence)
            old_part = old.parts[old_id]
            last_handled_old_id = old_id
            while "checking parts":
                # new_id >= old_id
                # Check for renamed parts, and step the new ID once
                if old_id == new_id:
                    # Handle renamed parts
                    if old_part["name"] != new_part["name"]:
                        # TODO: confirm part renaming counts as an API break
                        if not old.is_wip and not old_part["wip"]:
                            self.api_break = True
                        
                        changed_part = f"RENAMED ({old_id}): " + old_part['name']
                        if old_part["wip"]:
                            changed_part += "[WIP]"
                        changed_part += new_part["name"]
                        self.parts.append(part_name)

                    # Step to the next new part (if there is one)
                    try:
                        new_id = next(new_id_sequence)
                        new_part = new.parts[new_id]
                    except StopIteration:
                        # No new parts
                        if new_id == old_id:
                            return
                        # Only old, removed parts left at the end
                        self.parts.append(f"REMOVED({old_id}): " + old_part["name"] + "[WIP]" if old_part["wip"] else "")
                        for id in old_id_sequence:
                            removed_part = old.parts[id]
                            self.parts.append(f"REMOVED({id}): " removed_part["name"] + "[WIP]" if removed_part[id]["wip"] else "")
                        return

                # new_id > old_id
                # Step the old ID up to >= the new ID, recording any removed internal ones
                while new_id > old_id:
                    if old_id > last_handled_old_id:
                        removed_part = f"REMOVED ({old_id}): " + old_part["name"]
                        if old_part["wip"]:
                            removed_part += "[WIP]"
                        self.parts.append(removed_part)
                        # TODO: confirm part removal counts as an API break
                        if not old.is_wip and not old_part["wip"]:
                            self.api_break = True

                    # Try to progress to the next old part, if there is one
                    try:
                        old_id = next(old_id_sequence)
                        old_part = old.parts[old_id]
                        last_handled_old_id = old_id
                    except StopIteration:
                        # Only new parts left, at the end
                        self.parts.append(f"NEW ({new_id}): " + new_part["name"] + "[WIP]" if new_part["wip"] else "")
                        self.parts.extend(
                            f"NEW ({id}): " + new.parts[id]["name"] + "[WIP]" if new.parts[id]["wip"] else ""
                            for id in new_id_sequence
                        )
                        return

                # new_id <= old_id
                # Step the new ID up to >= the old ID, recording any internal extra ones
                while new_id < old_id:
                    self.parts.append(f"NEW ({new_id}): " + new_part["name"] + "[WIP]" if new_part["wip"] else "")
                    # New parts don't break an old API, so no need to set self.api_break

                    # Try to progress to the next new part, if there is one
                    try:
                        new_id = next(new_id_sequence)
                        new_part = new.parts[new_id]
                    except StopIteration:
                        # Only old, removed parts left at the end
                        self.parts.append(f"REMOVED({old_id}): " + old_part["name"] + "[WIP]" if old_part["wip"] else "")
                        for id in old_id_sequence:
                            removed_part = old.parts[id]
                            self.parts.append(f"REMOVED({id}): " removed_part["name"] + "[WIP]" if removed_part[id]["wip"] else "")
                        return

    def __str__(self):
        output = f"{self.name}("
        if self.parts:
            output += "\n\t" + "\n\t".join(self.parts) + "\n"
        output += ")"
        return output


def collect_components(root):
    """Collect all components and mark if they are WIP."""
    enums = {}
    messages = {}
    for index, enum in enumerate(root.findall(".//enum")):
        enums[enum.get("name")] = MAVLinkEnum(index, enum)
    for message in root.findall(".//message"):
        identifier = message.get("id")
        messages[identifier] = MAVLinkMessage(identifier, message)
    return enums, messages

def get_base_commit():
    return subprocess.check_output(
        ["git", "merge-base", "origin/master", "HEAD"], text=True
    ).strip()

def get_changed_xml_files(base):
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", base], text=True
    ).splitlines()
    return [f for f in changed if f.endswith(".xml")]

def parse_xml(content):
    return etree.fromstring(content.encode() if isinstance(content, str) else content)

def main():
    base = get_base_commit()
    xml_files = get_changed_xml_files(base)
    if not xml_files:
        print("No XML files changed.")
        return

    for xml in xml_files:
        if xml.endswith("development.xml"):
            continue

        try:
            old_content = subprocess.check_output(
                ["git", "show", f"{base}:{xml}"], text=True
            )
            new_content = open(xml).read()
        except subprocess.CalledProcessError:
            continue # new file or removed, ignore

        old_root = parse_xml(old_content)
        new_root = parse_xml(new_content)

        old_enums, old_messages = collect_components(old_root)
        new_enums, new_messages = collect_components(new_root)

        old_message_set = set(old_messages)
        new_message_set = set(new_messages)
        added_messages = {
            id: new_message_set[id]
            for id in new_message_set - old_message_set
        }
        removed_messages = {
            id: old_message_set[id]
            for id in old_message_set - new_message_set
        }

        modified_messages = {}
        maintained_messages = {}
        for identifier, new_message in new_messages.items():
            # Ignore completely new or removed messages
            if identifier in added or identifier in removed:
                continue
            old_message = old_messages[identifier]
            if old_message != new_message:
                modified_messages[identifier] = Delta(old_message, new_message)
            #else:
            #    maintained_messages[identifier] = old_message

        old_enums_set = set(old_enums)
        new_enums_set = set(new_enums)
        ... # WIP

        if renamed:
            print(f"Name changes detected in {xml}:")
            for name in renamed:
                print(f" - {name}")
            sys.exit(1)

    print("No name changes detected.")

if __name__ == "__main__":
    main()
