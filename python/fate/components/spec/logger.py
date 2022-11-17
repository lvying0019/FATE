import logging
import logging.config
import pathlib
from typing import Literal

import pydantic


class PipelineLogger(pydantic.BaseModel):
    class PipelineLoggerMetadata(pydantic.BaseModel):
        basepath: pydantic.DirectoryPath
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        debug_mode: bool = False

        @pydantic.validator("basepath", pre=True)
        def create_basepath(cls, value):
            pathlib.Path(value).mkdir(parents=True, exist_ok=True)
            return value

    type: Literal["pipeline"]
    metadata: PipelineLoggerMetadata

    def install(self):
        self.metadata.basepath.mkdir(parents=True, exist_ok=True)
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        formatters = {"brief": {"format": "'%(asctime)s %(levelname)-8s %(name)-15s %(message)s'"}}
        handlers = {}
        filters = {}

        def add_file_handler(
            name,
            filename,
            level,
            formater="brief",
            filters=[],
            max_bytes=102400,
            backup_count=3,
        ):
            handlers[name] = {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": formater,
                "filters": filters,
                "filename": filename,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
            }

        # add root logger
        root_handlers = []
        root_base_path = self.metadata.basepath.joinpath("root")
        root_base_path.mkdir(parents=True, exist_ok=True)
        for level in levels:
            handler_name = f"root_{level.lower()}"
            add_file_handler(
                name=handler_name,
                filename=root_base_path.joinpath(level),
                level=level,
            )
            root_handlers.append(handler_name)

        # add console logger
        if self.metadata.debug_mode:
            handler_name = f"root_console_{self.metadata.level.lower()}"
            handlers[handler_name] = {
                # "class": "logging.StreamHandler",
                "class": "rich.logging.RichHandler",
                # "formatter": "brief",
                "level": self.metadata.level,
                "filters": [],
                # "stream": "ext://sys.stdout",
            }
            root_handlers.append(handler_name)

        # add component logger
        component_handlers = []
        component_base_path = self.metadata.basepath.joinpath("component")
        component_base_path.mkdir(parents=True, exist_ok=True)
        filters["components"] = {"name": "fate.components"}
        filters["ml"] = {"name": "fate.ml"}
        for level in levels:
            handler_name = f"component_{level.lower()}"
            add_file_handler(
                name=handler_name,
                filename=component_base_path.joinpath(level),
                level=level,
            )
            component_handlers.append(handler_name)
        component_loggers = {
            "fate.components": dict(
                handlers=component_handlers,
                filters=["components"],
                level=self.metadata.level,
            ),
            "fate.ml": dict(
                handlers=component_handlers,
                filters=["ml"],
                level=self.metadata.level,
            ),
        }

        logging.config.dictConfig(
            dict(
                version=1,
                formatters=formatters,
                handlers=handlers,
                filters=filters,
                loggers=component_loggers,
                root=dict(handlers=root_handlers, level=self.metadata.level),
                disable_existing_loggers=False,
            )
        )


class FlowLogger(pydantic.BaseModel):
    class FlowLoggerMetadata(pydantic.BaseModel):
        basepath: pydantic.DirectoryPath
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    type: Literal["flow"]
    metadata: FlowLoggerMetadata

    def install(self):
        raise NotImplementedError()


class CustomLogger(pydantic.BaseModel):
    class CustomLoggerMetadata(pydantic.BaseModel):
        config_dict: dict

    type: Literal["custom"]
    metadata: CustomLoggerMetadata

    def install(self):
        logging.config.dictConfig(self.metadata.config_dict)
