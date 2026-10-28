package com.dsefa.flir;
import java.io.*;
import java.nio.file.*;
public final class StorageTest {
    public static void main(String[] args)throws Exception{
        File dir=Files.createTempDirectory("flir-budget-").toFile();
        File old=new File(dir,"FLIR-old.f1raw"),newer=new File(dir,"FLIR-new.f1raw"),other=new File(dir,"notes.txt"),active=new File(dir,"FLIR-active.f1raw");
        Files.write(old.toPath(),new byte[40]);Files.write(newer.toPath(),new byte[40]);Files.write(other.toPath(),new byte[99]);
        old.setLastModified(1000);newer.setLastModified(2000);
        StorageBudget b=new StorageBudget(dir,100);b.open(active);b.reserve(active,30);
        check(!old.exists()&&newer.exists()&&other.exists(),"only oldest completed RAW may be removed");
        b.reserve(active,60);check(!newer.exists(),"queued logical bytes must count before disk flush");
        boolean blocked=false;try{b.reserve(active,20);}catch(IOException e){blocked=true;}
        check(blocked&&other.exists(),"active record cannot exceed cap or delete unrelated file");
        b.release(active);check(StorageBudget.limitFromMb(1000)==1000000000L,"default 1 GB decimal");
        check(StorageBudget.limitFromMb(1)==100000000L&&StorageBudget.limitFromMb(999999)==10000000000L,"100 MB to 10 GB bounds");
        File outside=Files.createTempFile("flir-outside-",".f1raw").toFile();
        boolean refused=false;try{b.open(outside);}catch(IOException e){refused=true;}
        check(refused&&outside.exists(),"budget cannot target files outside recording directory");
        File sharedDir=Files.createTempDirectory("flir-shared-budget-").toFile();
        File held=new File(sharedDir,"FLIR-export.f1raw"),writing=new File(sharedDir,"FLIR-writing.f1raw"),latest=new File(sharedDir,"FLIR-latest.f1raw");
        Files.write(held.toPath(),new byte[40]);Files.write(writing.toPath(),new byte[30]);
        StorageBudget first=StorageBudget.shared(sharedDir,100);first.open(writing);first.reserve(writing,30);first.pin(held);
        StorageBudget recreated=StorageBudget.shared(sharedDir,100);recreated.open(latest);
        boolean protectedFiles=false;try{recreated.reserve(latest,40);}catch(IOException e){protectedFiles=true;}
        check(protectedFiles&&held.exists()&&writing.exists(),"export pin and draining writer must survive Activity recreation");
        recreated.restorePin(held);first.unpin(held);recreated.reserve(latest,40);
        check(!held.exists()&&writing.exists(),"released export may be pruned, active writer may not");
        first.release(writing);recreated.release(latest);
        File clipsDir=Files.createTempDirectory("flir-clip-budget-").toFile();
        File rawOld=new File(clipsDir,"FLIR-old.f1raw"),clipHeld=new File(clipsDir,"FLIR-held.f1clip"),clipNew=new File(clipsDir,"FLIR-new.f1clip"),unowned=new File(clipsDir,"other.f1clip");
        Files.write(rawOld.toPath(),new byte[40]);Files.write(clipHeld.toPath(),new byte[40]);Files.write(unowned.toPath(),new byte[90]);rawOld.setLastModified(1000);clipHeld.setLastModified(2000);
        StorageBudget clipsBudget=new StorageBudget(clipsDir,100);clipsBudget.pin(clipHeld);clipsBudget.open(clipNew);clipsBudget.reserve(clipNew,30);
        check(!rawOld.exists()&&clipHeld.exists()&&unowned.exists(),"clip storage counts RAW and protects pinned clips / unrelated names");
        clipsBudget.unpin(clipHeld);clipsBudget.reserve(clipNew,60);
        check(!clipHeld.exists()&&unowned.exists(),"completed clips are deletion candidates");clipsBudget.release(clipNew);
        System.out.println("PASS bounded RAW storage / oldest first / active protection / unrelated files / limits");
    }
    static void check(boolean v,String message){if(!v)throw new AssertionError(message);}
}
