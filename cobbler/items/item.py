"""
Cobbler module that contains the code for a generic Cobbler item.

Changelog:

V3.4.0 (unreleased):
    * (Re-)Added Cache implementation with the following new methods and properties:
        * ``cache``
        * ``inmemery``
        * ``clean_cache()``
    * Overhauled the parent/child system:
        * ``children`` is now inside ``item.py``.
        * ``tree_walk()`` was added.
        * ``logical_parent`` was added.
        * ``get_parent()`` was added which returns the internal reference that is used to return the object of the
          ``parent`` property.
    * Removed:
        * mgmt_classes
        * mgmt_parameters
V3.3.4 (unreleased):
    * No changes
V3.3.3:
    * Added:
        * ``grab_tree``
V3.3.2:
    * No changes
V3.3.1:
    * No changes
V3.3.0:
    * This release switched from pure attributes to properties (getters/setters).
    * Added:
        * ``depth``: int
        * ``comment``: str
        * ``owners``: Union[list, str]
        * ``mgmt_classes``: Union[list, str]
        * ``mgmt_classes``: Union[dict, str]
        * ``conceptual_parent``: Union[distro, profile]
    * Removed:
        * collection_mgr: collection_mgr
        * Remove unreliable caching:
            * ``get_from_cache()``
            * ``set_cache()``
            * ``remove_from_cache()``
    * Changed:
        * Constructor: Takes an instance of ``CobblerAPI`` instead of ``CollectionManager``.
        * ``children``: dict -> list
        * ``ctime``: int -> float
        * ``mtime``: int -> float
        * ``uid``: str
        * ``kernel_options``: dict -> Union[dict, str]
        * ``kernel_options_post``: dict -> Union[dict, str]
        * ``autoinstall_meta``: dict -> Union[dict, str]
        * ``fetchable_files``: dict -> Union[dict, str]
        * ``boot_files``: dict -> Union[dict, str]
V3.2.2:
    * No changes
V3.2.1:
    * No changes
V3.2.0:
    * No changes
V3.1.2:
    * No changes
V3.1.1:
    * No changes
V3.1.0:
    * No changes
V3.0.1:
    * No changes
V3.0.0:
    * Added:
        * ``collection_mgr``: collection_mgr
        * ``kernel_options``: dict
        * ``kernel_options_post``: dict
        * ``autoinstall_meta``: dict
        * ``fetchable_files``: dict
        * ``boot_files``: dict
        * ``template_files``: dict
        * ``name``: str
        * ``last_cached_mtime``: int
    * Changed:
        * Rename: ``cached_datastruct`` -> ``cached_dict``
    * Removed:
        * ``config``
V2.8.5:
    * Added:
        * ``config``: ?
        * ``settings``: settings
        * ``is_subobject``: bool
        * ``parent``: Union[distro, profile]
        * ``children``: dict
        * ``log_func``: collection_mgr.api.log
        * ``ctime``: int
        * ``mtime``: int
        * ``uid``: str
        * ``last_cached_mtime``: int
        * ``cached_datastruct``: str
"""

# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright 2006-2009, Red Hat, Inc and Others
# SPDX-FileCopyrightText: Michael DeHaan <michael.dehaan AT gmail>

import fnmatch
import pprint
import uuid
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, TypeVar, Union

from cobbler import enums, utils
from cobbler.cexceptions import CX
from cobbler.decorator import InheritableDictProperty, InheritableProperty, LazyProperty
from cobbler.items.abstract.base_item import BaseItem
from cobbler.utils import input_converters

if TYPE_CHECKING:
    from cobbler.api import CobblerAPI
    from cobbler.cobbler_collections.collection import ITEM_UNION
    from cobbler.items.abstract.base_item import ITEM
    from cobbler.items.distro import Distro
    from cobbler.items.menu import Menu
    from cobbler.items.profile import Profile
    from cobbler.items.system import System
    from cobbler.settings import Settings


T = TypeVar("T")


class Item(BaseItem, ABC):
    """
    An Item is a serializable thing that can appear in a Collection
    """

    # Constants
    TYPE_NAME = "generic"
    COLLECTION_TYPE = "generic"

    # Item types dependencies.
    # Used to determine descendants and cache invalidation.
    # Format: {"Item Type": [("Dependent Item Type", "Dependent Type attribute"), ..], [..]}
    TYPE_DEPENDENCIES: Dict[str, List[Tuple[str, str]]] = {
        "repo": [
            ("profile", "repos"),
        ],
        "distro": [
            ("profile", "distro"),
        ],
        "menu": [
            ("menu", "parent"),
            ("image", "menu"),
            ("profile", "menu"),
        ],
        "profile": [
            ("profile", "parent"),
            ("system", "profile"),
        ],
        "image": [
            ("system", "image"),
        ],
        "system": [],
    }

    # Defines a logical hierarchy of Item Types.
    # Format: {"Item Type": [("Previous level Type", "Attribute to go to the previous level",), ..],
    #                       [("Next level Item Type", "Attribute to move from the next level"), ..]}
    LOGICAL_INHERITANCE: Dict[
        str, Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]
    ] = {
        "distro": (
            [],
            [
                ("profile", "distro"),
            ],
        ),
        "profile": (
            [
                ("distro", "distro"),
            ],
            [
                ("system", "profile"),
            ],
        ),
        "image": (
            [],
            [
                ("system", "image"),
            ],
        ),
        "system": ([("image", "image"), ("profile", "profile")], []),
    }

    @classmethod
    def __find_compare(
        cls,
        from_search: Union[str, List[Any], Dict[Any, Any], bool],
        from_obj: Union[str, List[Any], Dict[Any, Any], bool],
    ) -> bool:
        """
        Only one of the two parameters shall be given in this method. If you give both ``from_obj`` will be preferred.

        :param from_search: Tries to parse this str in the format as a search result string.
        :param from_obj: Tries to parse this str in the format of an obj str.
        :return: True if the comparison succeeded, False otherwise.
        :raises TypeError: In case the type of one of the two variables is wrong or could not be converted
                           intelligently.
        """
        if isinstance(from_obj, str):
            # FIXME: fnmatch is only used for string to string comparisons which should cover most major usage, if
            #        not, this deserves fixing
            from_obj_lower = from_obj.lower()
            from_search_lower = from_search.lower()  # type: ignore
            # It's much faster to not use fnmatch if it's not needed
            if (
                "?" not in from_search_lower
                and "*" not in from_search_lower
                and "[" not in from_search_lower
            ):
                match = from_obj_lower == from_search_lower  # type: ignore
            else:
                match = fnmatch.fnmatch(from_obj_lower, from_search_lower)  # type: ignore
            return match  # type: ignore

        if isinstance(from_search, str):
            if isinstance(from_obj, list):
                from_search = input_converters.input_string_or_list(from_search)
                for list_element in from_search:
                    if list_element not in from_obj:
                        return False
                return True
            if isinstance(from_obj, dict):
                from_search = input_converters.input_string_or_dict(
                    from_search, allow_multiples=True
                )
                for dict_key in list(from_search.keys()):  # type: ignore
                    dict_value = from_search[dict_key]
                    if dict_key not in from_obj:
                        return False
                    if not (dict_value == from_obj[dict_key]):
                        return False
                return True
            if isinstance(from_obj, bool):  # type: ignore
                inp = from_search.lower() in ["true", "1", "y", "yes"]
                if inp == from_obj:
                    return True
                return False

        raise TypeError(f"find cannot compare type: {type(from_obj)}")

    def __init__(
        self, api: "CobblerAPI", *args: Any, is_subobject: bool = False, **kwargs: Any
    ):
        """
        Constructor.  Requires a back reference to the CobblerAPI object.

        NOTE: is_subobject is used for objects that allow inheritance in their trees. This inheritance refers to
        conceptual inheritance, not Python inheritance. Objects created with is_subobject need to call their
        setter for parent immediately after creation and pass in a value of an object of the same type. Currently this
        is only supported for profiles. Subobjects blend their data with their parent objects and only require a valid
        parent name and a name for themselves, so other required options can be gathered from items further up the
        Cobbler tree.

                           distro
                               profile
                                    profile  <-- created with is_subobject=True
                                         system   <-- created as normal
                           image
                               system
                           menu
                               menu

        For consistency, there is some code supporting this in all object types, though it is only usable
        (and only should be used) for profiles at this time.  Objects that are children of
        objects of the same type (i.e. subprofiles) need to pass this in as True.  Otherwise, just
        use False for is_subobject and the parent object will (therefore) have a different type.

        The keyword arguments are used to seed the object. This is the preferred way over ``from_dict`` starting with
        Cobbler version 3.4.0.

        :param api: The Cobbler API object which is used for resolving information.
        :param is_subobject: See above extensive description.
        """
        super().__init__(api, *args, **kwargs)

        self._parent = ""
        self._depth = 0
        self._children: List[str] = []
        self._kernel_options: Union[Dict[Any, Any], str] = {}
        self._kernel_options_post: Union[Dict[Any, Any], str] = {}
        self._autoinstall_meta: Union[Dict[Any, Any], str] = {}
        self._fetchable_files: Union[Dict[Any, Any], str] = {}
        self._boot_files: Union[Dict[Any, Any], str] = {}
        self._template_files: Dict[str, Any] = {}
        self._last_cached_mtime = 0
        self._is_subobject = is_subobject
        self._inmemory = True

        if len(kwargs) > 0:
            kwargs.update({"is_subobject": is_subobject})
            Item.from_dict(self, kwargs)
        if self._uid == "":
            self._uid = uuid.uuid4().hex

        if not self._has_initialized:
            self._has_initialized = True

    def __setattr__(self, name: str, value: Any):
        """
        Intercepting an attempt to assign a value to an attribute.

        :name: The attribute name.
        :value: The attribute value.
        """
        if Item._is_dict_key(name) and self._has_initialized:
            self.clean_cache(name)
        super().__setattr__(name, value)

    def __common_resolve(self, property_name: str):
        settings_name = property_name
        if property_name.startswith("proxy_url_"):
            property_name = "proxy"
        if property_name == "owners":
            settings_name = "default_ownership"
        attribute = "_" + property_name

        return getattr(self, attribute), settings_name

    def __resolve_get_parent_or_settings(self, property_name: str, settings_name: str):
        settings = self.api.settings()
        conceptual_parent = self.get_conceptual_parent()

        if hasattr(self.parent, property_name):
            return getattr(self.parent, property_name)
        elif hasattr(conceptual_parent, property_name):
            return getattr(conceptual_parent, property_name)
        elif hasattr(settings, settings_name):
            return getattr(settings, settings_name)
        elif hasattr(settings, f"default_{settings_name}"):
            return getattr(settings, f"default_{settings_name}")
        return None

    def _resolve(self, property_name: str) -> Any:
        """
        Resolve the ``property_name`` value in the object tree. This function traverses the tree from the object to its
        topmost parent and returns the first value that is not inherited. If the tree does not contain a value the
        settings are consulted.

        :param property_name: The property name to resolve.
        :raises AttributeError: In case one of the objects try to inherit from a parent that does not have
                                ``property_name``.
        :return: The resolved value.
        """
        attribute_value, settings_name = self.__common_resolve(property_name)

        if attribute_value == enums.VALUE_INHERITED:
            possible_return = self.__resolve_get_parent_or_settings(
                property_name, settings_name
            )
            if possible_return is not None:
                return possible_return
            raise AttributeError(
                f'{type(self)} "{self.name}" inherits property "{property_name}", but neither its parent nor'
                f" settings have it"
            )

        return attribute_value

    def _resolve_enum(
        self, property_name: str, enum_type: Type[enums.ConvertableEnum]
    ) -> Any:
        """
        See :meth:`~cobbler.items.item.Item._resolve`
        """
        attribute_value, settings_name = self.__common_resolve(property_name)
        unwrapped_value = getattr(attribute_value, "value", "")
        if unwrapped_value == enums.VALUE_INHERITED:
            possible_return = self.__resolve_get_parent_or_settings(
                unwrapped_value, settings_name
            )
            if possible_return is not None:
                return enum_type(possible_return)
            raise AttributeError(
                f'{type(self)} "{self.name}" inherits property "{property_name}", but neither its parent nor'
                f" settings have it"
            )

        return attribute_value

    def _resolve_dict(self, property_name: str) -> Dict[str, Any]:
        """
        Merge the ``property_name`` dictionary of the object with the ``property_name`` of all its parents. The value
        of the child takes precedence over the value of the parent.

        :param property_name: The property name to resolve.
        :return: The merged dictionary.
        :raises AttributeError: In case the the the object had no attribute with the name :py:property_name: .
        """
        attribute = "_" + property_name

        attribute_value = getattr(self, attribute)
        settings = self.api.settings()

        merged_dict: Dict[str, Any] = {}

        conceptual_parent = self.get_conceptual_parent()
        if hasattr(conceptual_parent, property_name):
            merged_dict.update(getattr(conceptual_parent, property_name))
        elif hasattr(settings, property_name):
            merged_dict.update(getattr(settings, property_name))

        if attribute_value != enums.VALUE_INHERITED:
            merged_dict.update(attribute_value)

        utils.dict_annihilate(merged_dict)
        return merged_dict

    def _deduplicate_dict(
        self, property_name: str, value: Dict[str, T]
    ) -> Dict[str, T]:
        """
        Filter out the key:value pair may come from parent and global settings.
        Note: we do not know exactly which resolver does key:value belongs to, what we did is just deduplicate them.

        :param property_name: The property name to deduplicated.
        :param value: The value that should be deduplicated.
        :returns: The deduplicated dictionary
        """
        _, settings_name = self.__common_resolve(property_name)
        settings = self.api.settings()
        conceptual_parent = self.get_conceptual_parent()

        if hasattr(self.parent, property_name):
            parent_value = getattr(self.parent, property_name)
        elif hasattr(conceptual_parent, property_name):
            parent_value = getattr(conceptual_parent, property_name)
        elif hasattr(settings, settings_name):
            parent_value = getattr(settings, settings_name)
        elif hasattr(settings, f"default_{settings_name}"):
            parent_value = getattr(settings, f"default_{settings_name}")
        else:
            parent_value = {}

        # Because we use getattr pyright cannot correctly check this.
        for key in parent_value:  # type: ignore
            if key in value and parent_value[key] == value[key]:  # type: ignore
                value.pop(key)  # type: ignore

        return value

    @InheritableDictProperty
    def kernel_options(self) -> Dict[Any, Any]:
        """
        Kernel options are a space delimited list, like 'a=b c=d e=f g h i=j' or a dict.

        .. note:: This property can be set to ``<<inherit>>``.

        :getter: The parsed kernel options.
        :setter: The new kernel options as a space delimited list. May raise ``ValueError`` in case of parsing problems.
        """
        return self._resolve_dict("kernel_options")

    @kernel_options.setter  # type: ignore[no-redef]
    def kernel_options(self, options: Dict[str, Any]):
        """
        Setter for ``kernel_options``.

        :param options: The new kernel options as a space delimited list.
        :raises ValueError: In case the values set could not be parsed successfully.
        """
        try:
            value = input_converters.input_string_or_dict(options, allow_multiples=True)
            if value == enums.VALUE_INHERITED:
                self._kernel_options = enums.VALUE_INHERITED
                return
            # pyright doesn't understand that the only valid str return value is this constant.
            self._kernel_options = self._deduplicate_dict("kernel_options", value)  # type: ignore
        except TypeError as error:
            raise TypeError("invalid kernel value") from error

    @InheritableDictProperty
    def kernel_options_post(self) -> Dict[str, Any]:
        """
        Post kernel options are a space delimited list, like 'a=b c=d e=f g h i=j' or a dict.

        .. note:: This property can be set to ``<<inherit>>``.

        :getter: The dictionary with the parsed values.
        :setter: Accepts str in above mentioned format or directly a dict.
        """
        return self._resolve_dict("kernel_options_post")

    @kernel_options_post.setter  # type: ignore[no-redef]
    def kernel_options_post(self, options: Union[Dict[Any, Any], str]) -> None:
        """
        Setter for ``kernel_options_post``.

        :param options: The new kernel options as a space delimited list.
        :raises ValueError: In case the options could not be split successfully.
        """
        try:
            self._kernel_options_post = input_converters.input_string_or_dict(
                options, allow_multiples=True
            )
        except TypeError as error:
            raise TypeError("invalid post kernel options") from error

    @InheritableDictProperty
    def autoinstall_meta(self) -> Dict[Any, Any]:
        """
        A comma delimited list of key value pairs, like 'a=b,c=d,e=f' or a dict.
        The meta tags are used as input to the templating system to preprocess automatic installation template files.

        .. note:: This property can be set to ``<<inherit>>``.

        :getter: The metadata or an empty dict.
        :setter: Accepts anything which can be split by :meth:`~cobbler.utils.input_converters.input_string_or_dict`.
        """
        return self._resolve_dict("autoinstall_meta")

    @autoinstall_meta.setter  # type: ignore[no-redef]
    def autoinstall_meta(self, options: Dict[Any, Any]):
        """
        Setter for the ``autoinstall_meta`` property.

        :param options: The new options for the automatic installation meta options.
        :raises ValueError: If splitting the value does not succeed.
        """
        value = input_converters.input_string_or_dict(options, allow_multiples=True)
        if value == enums.VALUE_INHERITED:
            self._autoinstall_meta = enums.VALUE_INHERITED
            return
        # pyright doesn't understand that the only valid str return value is this constant.
        self._autoinstall_meta = self._deduplicate_dict("autoinstall_meta", value)  # type: ignore

    @LazyProperty
    def template_files(self) -> Dict[Any, Any]:
        """
        File mappings for built-in configuration management. The keys are the template source files and the value is the
        destination. The destination must be inside the bootloc (most of the time TFTP server directory).

        :getter: The dictionary with name-path key-value pairs.
        :setter: A dict. If not a dict must be a str which is split by
                 :meth:`~cobbler.utils.input_converters.input_string_or_dict`. Raises ``TypeError`` otherwise.
        """
        return self._template_files

    @template_files.setter
    def template_files(self, template_files: Union[str, Dict[Any, Any]]) -> None:
        """
        A comma seperated list of source=destination templates that should be generated during a sync.

        :param template_files: The new value for the template files which are used for the item.
        :raises ValueError: In case the conversion from non dict values was not successful.
        """
        try:
            self._template_files = input_converters.input_string_or_dict_no_inherit(
                template_files, allow_multiples=False
            )
        except TypeError as error:
            raise TypeError("invalid template files specified") from error

    @LazyProperty
    def boot_files(self) -> Dict[Any, Any]:
        """
        Files copied into tftpboot beyond the kernel/initrd. These get rendered via Cheetah/Jinja and must be text
        based.

        :getter: The dictionary with name-path key-value pairs.
        :setter: A dict. If not a dict must be a str which is split by
                 :meth:`~cobbler.utils.input_converters.input_string_or_dict`. Raises ``TypeError`` otherwise.
        """
        return self._resolve_dict("boot_files")

    @boot_files.setter
    def boot_files(self, boot_files: Dict[Any, Any]) -> None:
        """
        A comma separated list of req_name=source_file_path that should be fetchable via tftp.

        .. note:: This property can be set to ``<<inherit>>``.

        :param boot_files: The new value for the boot files used by the item.
        """
        try:
            self._boot_files = input_converters.input_string_or_dict(
                boot_files, allow_multiples=False
            )
        except TypeError as error:
            raise TypeError("invalid boot files specified") from error

    @InheritableDictProperty
    def fetchable_files(self) -> Dict[Any, Any]:
        """
        A comma seperated list of ``virt_name=path_to_template`` that should be fetchable via tftp or a webserver

        .. note:: This property can be set to ``<<inherit>>``.

        :getter: The dictionary with name-path key-value pairs.
        :setter: A dict. If not a dict must be a str which is split by
                 :meth:`~cobbler.utils.input_converters.input_string_or_dict`. Raises ``TypeError`` otherwise.
        """
        return self._resolve_dict("fetchable_files")

    @fetchable_files.setter  # type: ignore[no-redef]
    def fetchable_files(self, fetchable_files: Union[str, Dict[Any, Any]]):
        """
        Setter for the fetchable files.

        :param fetchable_files: Files which will be made available to external users.
        """
        try:
            self._fetchable_files = input_converters.input_string_or_dict(
                fetchable_files, allow_multiples=False
            )
        except TypeError as error:
            raise TypeError("invalid fetchable files specified") from error

    @LazyProperty
    def depth(self) -> int:
        """
        This represents the logical depth of an object in the category of the same items. Important for the order of
        loading items from the disk and other related features where the alphabetical order is incorrect for sorting.

        :getter: The logical depth of the object.
        :setter: The new int for the logical object-depth.
        """
        return self._depth

    @depth.setter
    def depth(self, depth: int) -> None:
        """
        Setter for depth.

        :param depth: The new value for depth.
        """
        if not isinstance(depth, int):  # type: ignore
            raise TypeError("depth needs to be of type int")
        self._depth = depth

    @LazyProperty
    def parent(self) -> Optional[Union["System", "Profile", "Distro", "Menu"]]:
        """
        This property contains the name of the parent of an object. In case there is not parent this return
        None.

        :getter: Returns the parent object or None if it can't be resolved via the Cobbler API.
        :setter: The name of the new logical parent.
        """
        if self._parent == "":
            return None
        return self.api.get_items(self.COLLECTION_TYPE).get(self._parent)  # type: ignore

    @parent.setter
    def parent(self, parent: str) -> None:
        """
        Set the parent object for this object.

        :param parent: The new parent object. This needs to be a descendant in the logical inheritance chain.
        """
        if not isinstance(parent, str):  # type: ignore
            raise TypeError('Property "parent" must be of type str!')
        if not parent:
            self._parent = ""
            return
        if parent == self.name:
            # check must be done in two places as setting parent could be called before/after setting name...
            raise CX("self parentage is weird")
        found = self.api.get_items(self.COLLECTION_TYPE).get(parent)
        if found is None:
            raise CX(f'profile "{parent}" not found, inheritance not possible')
        self._parent = parent
        self.depth = found.depth + 1

    @LazyProperty
    def get_parent(self) -> str:
        """
        This method returns the name of the parent for the object. In case there is not parent this return
        empty string.
        """
        return self._parent

    def get_conceptual_parent(self) -> Optional["ITEM_UNION"]:
        """
        The parent may just be a superclass for something like a subprofile. Get the first parent of a different type.

        :return: The first item which is conceptually not from the same type.
        """
        if self is None:  # type: ignore
            return None

        curr_obj = self
        next_obj = curr_obj.parent
        while next_obj is not None:
            curr_obj = next_obj
            next_obj = next_obj.parent

        if curr_obj.TYPE_NAME in curr_obj.LOGICAL_INHERITANCE:
            for prev_level in curr_obj.LOGICAL_INHERITANCE[curr_obj.TYPE_NAME][0]:
                prev_level_type = prev_level[0]
                prev_level_name = getattr(curr_obj, "_" + prev_level[1])
                if prev_level_name is not None and prev_level_name != "":
                    prev_level_item = self.api.find_items(
                        prev_level_type, name=prev_level_name, return_list=False
                    )
                    if prev_level_item is not None and not isinstance(
                        prev_level_item, list
                    ):
                        return prev_level_item
        return None

    @property
    def logical_parent(self) -> Any:
        """
        This property contains the name of the logical parent of an object. In case there is not parent this return
        None.

        :getter: Returns the parent object or None if it can't be resolved via the Cobbler API.
        :setter: The name of the new logical parent.
        """
        parent = self.parent
        if parent is None:
            return self.get_conceptual_parent()
        return parent

    @property
    def children(self) -> List["ITEM_UNION"]:
        """
        The list of logical children of any depth.
        :getter: An empty list in case of items which don't have logical children.
        :setter: Replace the list of children completely with the new provided one.
        """
        results: List[Any] = []
        list_items = self.api.get_items(self.COLLECTION_TYPE)
        for obj in list_items:
            if obj.get_parent == self._name:
                results.append(obj)
        return results

    def tree_walk(self) -> List["ITEM_UNION"]:
        """
        Get all children related by parent/child relationship.
        :return: The list of children objects.
        """
        results: List[Any] = []
        for child in self.children:
            results.append(child)
            results.extend(child.tree_walk())

        return results

    @property
    def descendants(self) -> List["ITEM_UNION"]:
        """
        Get objects that depend on this object, i.e. those that would be affected by a cascading delete, etc.

        .. note:: This is a read only property.

        :getter: This is a list of all descendants. May be empty if none exist.
        """
        childs = self.tree_walk()
        results = set(childs)
        childs.append(self)  # type: ignore
        for child in childs:
            for item_type in Item.TYPE_DEPENDENCIES[child.COLLECTION_TYPE]:
                dep_type_items = self.api.find_items(
                    item_type[0], {item_type[1]: child.name}, return_list=True
                )
                if dep_type_items is None or not isinstance(dep_type_items, list):
                    raise ValueError("Expected list to be returned by find_items")
                results.update(dep_type_items)
                for dep_item in dep_type_items:
                    results.update(dep_item.descendants)
        return list(results)

    @LazyProperty
    def is_subobject(self) -> bool:
        """
        Weather the object is a subobject of another object or not.

        :getter: True in case the object is a subobject, False otherwise.
        :setter: Sets the value. If this is not a bool, this will raise a ``TypeError``.
        """
        return self._is_subobject

    @is_subobject.setter
    def is_subobject(self, value: bool) -> None:
        """
        Setter for the property ``is_subobject``.

        :param value: The boolean value whether this is a subobject or not.
        :raises TypeError: In case the value was not of type bool.
        """
        if not isinstance(value, bool):  # type: ignore
            raise TypeError(
                "Field is_subobject of object item needs to be of type bool!"
            )
        self._is_subobject = value

    def sort_key(self, sort_fields: List[Any]):
        """
        Convert the item to a dict and sort the data after specific given fields.

        :param sort_fields: The fields to sort the data after.
        :return: The sorted data.
        """
        data = self.to_dict()
        return [data.get(x, "") for x in sort_fields]

    def find_match(self, kwargs: Dict[str, Any], no_errors: bool = False) -> bool:
        """
        Find from a given dict if the item matches the kv-pairs.

        :param kwargs: The dict to match for in this item.
        :param no_errors: How strict this matching is.
        :return: True if matches or False if the item does not match.
        """
        # used by find() method in collection.py
        data = self.to_dict()
        for (key, value) in list(kwargs.items()):
            # Allow ~ to negate the compare
            if value is not None and value.startswith("~"):
                res = not self.find_match_single_key(data, key, value[1:], no_errors)
            else:
                res = self.find_match_single_key(data, key, value, no_errors)
            if not res:
                return False

        return True

    def find_match_single_key(
        self, data: Dict[str, Any], key: str, value: Any, no_errors: bool = False
    ) -> bool:
        """
        Look if the data matches or not. This is an alternative for ``find_match()``.

        :param data: The data to search through.
        :param key: The key to look for int the item.
        :param value: The value for the key.
        :param no_errors: How strict this matching is.
        :return: Whether the data matches or not.
        """
        # special case for systems
        key_found_already = False
        if "interfaces" in data:
            if key in [
                "cnames",
                "connected_mode",
                "if_gateway",
                "ipv6_default_gateway",
                "ipv6_mtu",
                "ipv6_prefix",
                "ipv6_secondaries",
                "ipv6_static_routes",
                "management",
                "mtu",
                "static",
                "mac_address",
                "ip_address",
                "ipv6_address",
                "netmask",
                "virt_bridge",
                "dhcp_tag",
                "dns_name",
                "static_routes",
                "interface_type",
                "interface_master",
                "bonding_opts",
                "bridge_opts",
                "interface",
            ]:
                key_found_already = True
                for (name, interface) in list(data["interfaces"].items()):
                    if value == name:
                        return True
                    if value is not None and key in interface:
                        if self.__find_compare(interface[key], value):
                            return True

        if key not in data:
            if not key_found_already:
                if not no_errors:
                    # FIXME: removed for 2.0 code, shouldn't cause any problems to not have an exception here?
                    # raise CX("searching for field that does not exist: %s" % key)
                    return False
            else:
                if value is not None:  # FIXME: new?
                    return False

        if value is None:
            return True
        return self.__find_compare(value, data[key])

    def dump_vars(
        self, formatted_output: bool = True, remove_dicts: bool = False
    ) -> Union[Dict[str, Any], str]:
        """
        Dump all variables.

        :param formatted_output: Whether to format the output or not.
        :param remove_dicts: If True the dictionaries will be put into str form.
        :return: The raw or formatted data.
        """
        raw = utils.blender(self.api, remove_dicts, self)  # type: ignore
        if formatted_output:
            return pprint.pformat(raw)
        return raw

    def deserialize(self) -> None:
        """
        Deserializes the object itself and, if necessary, recursively all the objects it depends on.
        """

        def deserialize_ancestor(ancestor_item_type: str, ancestor_name: str):
            if ancestor_name not in {"", enums.VALUE_INHERITED}:
                ancestor = self.api.get_items(ancestor_item_type).get(ancestor_name)
                if ancestor is not None and not ancestor.inmemory:
                    ancestor.deserialize()

        if not self._has_initialized:
            return

        item_dict = self.api.deserialize_item(self)
        if item_dict["inmemory"]:
            for ancestor_item_type, ancestor_deps in Item.TYPE_DEPENDENCIES.items():
                for ancestor_dep in ancestor_deps:
                    if self.TYPE_NAME == ancestor_dep[0]:
                        attr_name = ancestor_dep[1]
                        if attr_name not in item_dict:
                            continue
                        attr_val = item_dict[attr_name]
                        if isinstance(attr_val, str):
                            deserialize_ancestor(ancestor_item_type, attr_val)
                        elif isinstance(attr_val, list):  # type: ignore
                            attr_val: List[str]
                            for ancestor_name in attr_val:
                                deserialize_ancestor(ancestor_item_type, ancestor_name)
        self.from_dict(item_dict)

    def grab_tree(self) -> List[Union["ITEM", "Settings"]]:
        """
        Climb the tree and get every node.

        :return: The list of items with all parents from that object upwards the tree. Contains at least the item
                 itself and the settings of Cobbler.
        """
        results: List[Union["ITEM", "Settings"]] = [self]
        parent = self.logical_parent
        while parent is not None:
            results.append(parent)
            parent = parent.logical_parent
            # FIXME: Now get the object and check its existence
        results.append(self.api.settings())
        self.logger.debug(
            "grab_tree found %s children (including settings) of this object",
            len(results),
        )
        return results

    def _clean_dict_cache(self, name: Optional[str]):
        """
        Clearing the Item dict cache.

        :param name: The name of Item attribute or None.
        """
        if not self.api.settings().cache_enabled:
            return

        if name is not None and self._inmemory:
            attr = getattr(type(self), name[1:])
            if (
                isinstance(attr, (InheritableProperty, InheritableDictProperty))
                and self.COLLECTION_TYPE != Item.COLLECTION_TYPE
                and self.api.get_items(self.COLLECTION_TYPE).get(self.name) is not None
            ):
                # Invalidating "resolved" caches
                for dep_item in self.descendants:
                    dep_item.cache.set_dict_cache(None, True)

        # Invalidating the cache of the object itself.
        self.cache.clean_dict_cache()
