from typing import Annotated, Union

from pydantic import Field

from service.schemas.backlog import CreateBacklogJobRequest
from service.schemas.qa import CreateQaJobRequest
from service.schemas.sdd import CreateSddJobRequest

CreateJobRequest = Annotated[
    Union[CreateQaJobRequest, CreateSddJobRequest, CreateBacklogJobRequest],
    Field(discriminator="flow"),
]
