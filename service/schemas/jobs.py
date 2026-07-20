from typing import Annotated, Union

from pydantic import Field

from service.schemas.qa import CreateQaJobRequest
from service.schemas.sdd import CreateSddJobRequest

CreateJobRequest = Annotated[
    Union[CreateQaJobRequest, CreateSddJobRequest],
    Field(discriminator="flow"),
]
