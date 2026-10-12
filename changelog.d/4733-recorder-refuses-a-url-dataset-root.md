### Fixed: a dataset `root=` or `repo_id` that is a URL is refused, not resolved to a folder named after the scheme

`resolve_dataset_dir` used an explicit `root` verbatim as `Path(root)`, and
`Path` reads a URL as a relative path: `root="s3://bucket/datasets/run1"`
resolved to `s3:/bucket/datasets/run1`, which `LeRobotDataset.create` then
created (`mkdir(parents=True)`) under the working directory. A recording
through `DatasetRecorder.create` or a backend's `start_recording` then failed
at its first `save_episode`, because pyarrow reads that path as an S3 URI
(`Missing bucket name in S3 URI`): the episode was lost and a stray `s3:`
folder stayed behind. An `s3://` `repo_id` with no root resolved to
`$HF_LEROBOT_HOME/s3:/bucket/datasets/run1`, where the episodes were written -
not in the store the caller named. The writers' shared resolver now refuses a
`root` or `repo_id` that opens with a URL scheme, before anything is created or
launched, naming the value, the local path `Path()` reads it as, and the
two-step remedy: record to a local root, then `sync_to_bucket()` or
`push_to_hub()` the finished directory. A URL `repo_id` is refused beside a
usable local `root` too: that call used to record into the root, where
`sync_to_bucket()` could upload it but `push_to_hub()` could not
(`huggingface_hub` refuses a URL as a repo id). A local path that merely
contains a `:` (`s3:/bucket/run1`, `run_s3://x`) is still a directory and still
resolves, and the `s3://` URIs a SageMaker training spec takes are untouched -
those address a managed job's input, not a local recording.
