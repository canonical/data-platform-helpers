PIP Package for a variety of Data Platform Helpers

Table of Contents:
1. Version Checker


### 1. Version Checker
#### Purpose: 
used to determine if a relevant version attribute across related applications are valid.

There are many potential applications for this. Here are a few examples:
1. in a sharded cluster where is is important that the shards and cluster manager have the same
components.
2. kafka connect and kafka broker apps working together and needing to have the same ubnderlying
version.

#### How to use:

0. add to requirements 
    in `requirements.txt`:

    ```
        data-platform-helpers==0.1.1
    ```
1. in `src/charm.py` of requirer + provider

    in constructor [REQUIRED]:

    ```
    from data_platform_helpers.version_check import CrossAppVersionChecker
    ...
    self.version_checker = self.CrossAppVersionChecker(
        self,
        version=x, # can be a revision of a charm, version of a snap, version of a workload, etc
        relations_to_check=[x,y,z],
        # only use if the version doesn't not need to exactly match our current version
        version_validity_range={"x": "<a,>b"})
    ```

    in update status hook [OPTIONAL]:

    ```
    if not self.version_checker.are_related_apps_valid():
        logger.debug(
            "Warning relational version check failed, these relations have mismatched versions",
            "%s",
            self.version_checker(self.version_checker.get_invalid_versions())
        )
        # do something, ie set status, instruct user to change something, etc
    ```

2. other areas of the charm (i.e. joined events, action events, etc) [OPTIONAL]:
    ```
    if not self.charm.version_checker.are_related_apps_valid():
        # do something - i.e. fail event or log message
    ```
3. in upgrade handler of requirer + provider [REQUIRED]:
    ```
    if [last unit to upgrade]:
        self.charm.version.set_version_across_all_relations()
    ```
